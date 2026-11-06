import string, random
import secrets
import json
import ast
import io
import qrcode
import base64
import logging
import requests
from django.urls import reverse
from django.db import transaction, models
from django.db.models import F
from django.utils import timezone
from Events.models import OrderTicket, TicketPrice, OrderStatus
from Transactions.models import Payment, SoldTicket, TicketStatus
from Users.models import User
from django.conf import settings
from celery import shared_task
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
import pdfkit
from .utils import format_date

logger = logging.getLogger(__name__)


def safe_parse_list(val):
    if isinstance(val, list):
        return val
    if not val:
        return []
    if isinstance(val, str):
        val = val.strip()
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        try:
            parsed = ast.literal_eval(val)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
        return [val] if val else []
    return []


def generate_ref_code():
    return secrets.token_hex(10).upper()


def generate_key():
    return ''.join(secrets.choice(string.digits) for _ in range(16))


def generate_ticket_number():
    return f"TKT-{secrets.token_hex(4).upper()}"


def generate_qr_token():
    return f"tkt_sec_{secrets.token_urlsafe(32)}"
    

def generate_pdf(html):
    return pdfkit.from_string(html)


def generate_qrcode(data):
    qr = qrcode.QRCode(box_size=5)
    qr.add_data(data)
    qr.make(fit=True)
    buffer = io.BytesIO()
    img = qr.make_image(fill_color='black', back_color='white')
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def get_base_url():
    hosts = getattr(settings, 'ALLOWED_HOSTS', [])
    if hosts and hosts[0] != '*':
        host = hosts[0].rstrip('/')
        return host if host.startswith('http') else f"http://{host}"
    return getattr(settings, 'FRONTEND_URL', 'http://localhost:8000').rstrip('/')



def create_ticket(email, user_id, bought_ticket_id, payment_id):   
    user = User.objects.get(id=user_id)
    bought_ticket = OrderTicket.objects.get(id=bought_ticket_id, status='completed')
    payment = Payment.objects.get(id=payment_id)
    event = bought_ticket.event
    name = event.name
    address = f'{event.address} {event.state} {event.country}'
    date = format_date(event.start_date, event.end_date)
    base_url = get_base_url()

    if email is None: # send the tickets to the multiple emails the user provided
        for buy_ticket in bought_ticket.tickets.all():
            emails = safe_parse_list(buy_ticket.emails)
            tier = buy_ticket.event_ticket
            for recipient_email in emails:
                key = generate_key()
                ticket_number = generate_ticket_number()
                qr_code_token = generate_qr_token()

                sold_ticket = SoldTicket.objects.create(
                    user=user,
                    payment=payment,
                    event=bought_ticket,
                    ticket=tier,
                    key=key,
                    ticket_number=ticket_number,
                    qr_code_token=qr_code_token,
                    status=TicketStatus.ISSUED,
                    used=False
                )
                verify_path = reverse('verify-qrcode', kwargs={'key': key, 'event': event.id})
                url = f"{base_url}{verify_path}?token={qr_code_token}"
                qrcode_img = generate_qrcode(url)
                context = {
                    'event': name,
                    'data': None,
                    'qrcode': qrcode_img,
                    'date': date,
                    'address': address,
                    'label': tier.label,
                    'ticket_number': ticket_number
                }
                template = render_to_string('pdf.html', context)
                pdf = generate_pdf(template)
                subject = '[TicketPlug] Purchased Tickets 🎉'
                text_content = f'Thanks for Purchasing with Us. Your ticket number is {ticket_number}.\n'
                html_context = {'event': name, 'address': address, 'label': tier.label, 'date': date, 'ticket_number': ticket_number}
                html_content = render_to_string('ticket.html', html_context)
                msg = EmailMultiAlternatives(subject, text_content, settings.EMAIL_HOST_USER, [recipient_email])
                msg.attach_alternative(html_content, "text/html")
                msg.attach(f'{name}_ticket_{ticket_number}.pdf', pdf)
                msg.send()
    else: # send the tickets to the single email the user provided during payment
        data = [] 
        for buy_ticket in bought_ticket.tickets.all():
            tier = buy_ticket.event_ticket
            for _ in range(buy_ticket.qty):
                key = generate_key()
                ticket_number = generate_ticket_number()
                qr_code_token = generate_qr_token()

                sold_ticket = SoldTicket.objects.create(
                    user=user,
                    payment=payment,
                    event=bought_ticket,
                    ticket=tier,
                    key=key,
                    ticket_number=ticket_number,
                    qr_code_token=qr_code_token,
                    status=TicketStatus.ISSUED,
                    used=False
                )
                verify_path = reverse('verify-qrcode', kwargs={'key': key, 'event': event.id})
                url = f"{base_url}{verify_path}?token={qr_code_token}"
                qrcode_img = generate_qrcode(url)
                context = {
                    'event': name,
                    'qrcode': qrcode_img,
                    'date': date,
                    'address': address,
                    'label': tier.label,
                    'ticket_number': ticket_number
                }
                data.append(context) 

        html = render_to_string('pdf.html', {'data': data})      
        subject = '[TicketPlug] Purchased Tickets 🎉'
        text_content = 'Thanks for Purchasing with Us \n' 
        html_context = {'event': name, 'address': address, 'date': date} 
        html_content = render_to_string('ticket.html', html_context)
        msg = EmailMultiAlternatives(subject, text_content, settings.EMAIL_HOST_USER, [email])
        pdfs = generate_pdf(html)
        msg.attach_alternative(html_content, "text/html")
        msg.attach(f'{name}_tickets.pdf', pdfs)
        msg.send()


@shared_task
def create_payment_record(bought_ticket_id, amount, user_id, email, paystack_ref=None):
    """
    Generate payment record and dispatch ticket generation.
    Handles inventory transition from RESERVED to sold, and manages late-payment edge cases.
    Protected by atomic database transaction.
    """
    ref_code = paystack_ref or generate_ref_code()
    try:
        user = User.objects.get(id=user_id)
        with transaction.atomic():
            bought_ticket = OrderTicket.objects.select_for_update().get(id=bought_ticket_id)

            if bought_ticket.status in ['completed', OrderStatus.COMPLETED]:
                logger.info(f"Order {bought_ticket_id} already marked completed. Skipping.")
                return

            # LATE-PAYMENT EDGE CASE HANDLING:
            if bought_ticket.status == OrderStatus.EXPIRED:
                logger.warning(f"Payment received for EXPIRED order {bought_ticket_id}. Checking for inventory re-allocation.")
                can_fulfill = True
                for buy_ticket in bought_ticket.tickets.all():
                    tier = TicketPrice.objects.select_for_update().get(id=buy_ticket.event_ticket_id)
                    if tier.get_tickets_available() < buy_ticket.qty:
                        can_fulfill = False
                        break

                if not can_fulfill:
                    logger.error(f"Cannot fulfill late payment for order {bought_ticket_id}: inventory sold out. Triggering refund.")
                    bought_ticket.status = OrderStatus.CANCELLED
                    bought_ticket.save(update_fields=['status'])

                    # Auto-refund via Paystack if possible
                    if paystack_ref and getattr(settings, 'PAYSTACK_SECRET_KEY', None):
                        try:
                            refund_url = 'https://api.paystack.co/refund'
                            headers = {'authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'}
                            refund_resp = requests.post(
                                refund_url,
                                timeout=30,
                                headers=headers,
                                json={'transaction': paystack_ref, 'amount': int(amount * 100), 'merchant_note': 'Order reservation expired and inventory sold out.'}
                            )
                            logger.info(f"Paystack refund initiated for order {bought_ticket_id}: {refund_resp.status_code}")
                        except Exception as refund_err:
                            logger.error(f"Failed to auto-refund order {bought_ticket_id}: {refund_err}")

                    subject = '[TicketPlug] Order Expired - Payment Refunded'
                    msg_body = f"Hello,\n\nWe received payment for your order, but your 15-minute reservation had expired and the event was sold out.\n\nA refund of NGN {amount} has been initiated to your original payment method.\n\nTicketPlug Team"
                    msg = EmailMultiAlternatives(subject, msg_body, settings.EMAIL_HOST_USER, [email])
                    msg.send()
                    return

                # If inventory is available, re-allocate directly to sold
                for buy_ticket in bought_ticket.tickets.all():
                    tier = TicketPrice.objects.select_for_update().get(id=buy_ticket.event_ticket_id)
                    tier.sold = F('sold') + buy_ticket.qty
                    tier.save()
                    buy_ticket.completed = True
                    buy_ticket.save()

            else:
                # Normal reservation path (RESERVED or 'not completed')
                # Atomically decrement reserved and increment sold
                for buy_ticket in bought_ticket.tickets.all():
                    tier = TicketPrice.objects.select_for_update().get(id=buy_ticket.event_ticket_id)
                    tier.reserved = models.Case(
                        models.When(reserved__gte=buy_ticket.qty, then=models.F('reserved') - buy_ticket.qty),
                        default=0
                    )
                    tier.sold = F('sold') + buy_ticket.qty
                    tier.save()
                    buy_ticket.completed = True
                    buy_ticket.save()

            payment, _ = Payment.objects.get_or_create(
                ticket=bought_ticket,
                defaults={'user': user, 'amount': amount, 'payment_id': ref_code}
            )
            bought_ticket.status = 'completed'
            bought_ticket.save(update_fields=['status'])

        create_ticket(email=email, bought_ticket_id=bought_ticket_id, payment_id=payment.id, user_id=user_id)
    except Exception as e:
        logger.error(f"Error creating payment record for order {bought_ticket_id}: {e}", exc_info=True)


@shared_task
def release_expired_ticket_reservations():
    """
    Periodic task (run every 60s by Celery Beat).
    Finds all orders in RESERVED status whose 15-minute window has passed.
    Atomically restores reserved inventory to available stock and marks orders EXPIRED.
    """
    now = timezone.now()
    with transaction.atomic():
        expired_orders = OrderTicket.objects.select_for_update(skip_locked=True).filter(
            status=OrderStatus.RESERVED,
            reservation_expires_at__lt=now
        )
        for order in expired_orders:
            for buy_ticket in order.tickets.filter(completed=False):
                if buy_ticket.event_ticket:
                    TicketPrice.objects.filter(id=buy_ticket.event_ticket_id).update(
                        reserved=models.Case(
                            models.When(reserved__gte=buy_ticket.qty, then=models.F('reserved') - buy_ticket.qty),
                            default=0
                        )
                    )
            order.status = OrderStatus.EXPIRED
            order.save(update_fields=['status'])
            logger.info(f"Released expired reservation for order {order.id}")


@shared_task
def payment_failed(bought_ticket_id, amount, user_id, email):
    """
    Cleans up pending tickets and releases reserved inventory if payment fails.
    """
    try:
        with transaction.atomic():
            order = OrderTicket.objects.filter(id=bought_ticket_id).exclude(status__in=['completed', OrderStatus.COMPLETED]).first()
            if order:
                for buy_ticket in order.tickets.filter(completed=False):
                    if buy_ticket.event_ticket:
                        TicketPrice.objects.filter(id=buy_ticket.event_ticket_id).update(
                            reserved=models.Case(
                                models.When(reserved__gte=buy_ticket.qty, then=models.F('reserved') - buy_ticket.qty),
                                default=0
                            )
                        )
                order.tickets.all().delete()
                order.status = OrderStatus.CANCELLED
                order.save(update_fields=['status'])
    except Exception as e:
        logger.error(f"Error handling failed payment for order {bought_ticket_id}: {e}", exc_info=True)

        




import string, random
import secrets
import json
import ast
import io
import qrcode
import base64
import logging
from django.urls import reverse
from django.db import transaction
from django.db.models import F
from Events.models import OrderTicket
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
    Protected by database transaction.
    """
    ref_code = paystack_ref or generate_ref_code()
    try:
        user = User.objects.get(id=user_id)
        with transaction.atomic():
            bought_ticket = OrderTicket.objects.get(id=bought_ticket_id, status='not completed')
            payment, _ = Payment.objects.get_or_create(
                ticket=bought_ticket,
                defaults={'user': user, 'amount': amount, 'payment_id': ref_code}
            )
            bought_ticket.status = 'completed'
            for buy_ticket in bought_ticket.tickets.all():
                buy_ticket.event_ticket.sold = F('sold') + buy_ticket.qty
                buy_ticket.event_ticket.save()
                buy_ticket.completed = True
                buy_ticket.save()
            bought_ticket.save()

        create_ticket(email=email, bought_ticket_id=bought_ticket_id, payment_id=payment.id, user_id=user_id)
    except Exception as e:
        logger.error(f"Error creating payment record for order {bought_ticket_id}: {e}", exc_info=True)


@shared_task
def payment_failed(bought_ticket_id, amount, user_id, email):
    """
    Cleans up pending tickets if payment fails.
    """
    try:
        order = OrderTicket.objects.filter(id=bought_ticket_id, status='not completed').first()
        if order:
            order.tickets.all().delete()
    except Exception as e:
        logger.error(f"Error handling failed payment for order {bought_ticket_id}: {e}", exc_info=True)

        




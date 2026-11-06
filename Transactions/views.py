import hmac
import hashlib
import logging
import requests
from django.conf import settings
from django.db import transaction, models
from django.utils import timezone
from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from Events.models import OrderTicket, OrderStatus
from .models import SoldTicket, Payment, CheckInLog, TicketStatus, CheckInResult
from .serializers import PaymentSErializer, CheckoutSerializer
from .tasks import create_payment_record, payment_failed

logger = logging.getLogger(__name__)

class Makepayment(APIView):
    '''
    endpoint to make payment, if the user is sending the tickets to only one email it should be put in the email field
    '''
    serializer_class =PaymentSErializer
    def get_serializer(self):
        return PaymentSErializer()

    def get(self , *args, **kwargs):
        user=self.request.user
        id= self.kwargs["pk"]
        try:
            order=OrderTicket.objects.get(id=id, user=user, status__in=['not completed', OrderStatus.RESERVED])
            if order.is_expired():
                return Response({"error": "Order reservation has expired. Please select your tickets again."}, status=status.HTTP_400_BAD_REQUEST)
            return Response(CheckoutSerializer(order).data)
        except Exception:
            return Response({"error":" invalid id or you dont have any tickets for this event"}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, *args, **kwargs):
        serializer=self.serializer_class(data=self.request.data)
        pk=self.kwargs['pk']
        order=OrderTicket.objects.filter(user=self.request.user, id=pk, status__in=['not completed', OrderStatus.RESERVED]).first()
        if order:
            if order.is_expired():
                return Response({"error": "Order reservation has expired. Please select your tickets again."}, status=status.HTTP_400_BAD_REQUEST)

            if serializer.is_valid(raise_exception=True):
                price=order.get_total_price()
                user=self.request.user
                user_id=str(user.id)
                email=serializer.validated_data.get('email')
                user_email=str(user.email)
                if price == 0:
                     create_payment_record.delay(amount=price, email=email, user_id=user_id, bought_ticket_id=pk)
                     return Response({"message" :"checkout successful, check your email to find your tickets"}) 
                else:    
                  url='https://api.paystack.co/transaction/initialize'
                  header={'authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'}
                  try:
                    resp=requests.post(url, timeout=100, headers=header, json={'amount':price*100, 'email':user_email, 'metadata':{'user_id':str(user.id), 'bought_ticket_id':str(pk), 'price':price,'email':email, },})
                    return Response(resp.json())
                  except Exception as e:
                    return Response({'error': f'{e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'error':'invalid uuid or you have not selected a ticket yet'}, status=status.HTTP_404_NOT_FOUND)

class PayStack_Webhook(APIView):
    permission_classes = []
    authentication_classes = []
    swagger_schema = None

    def post(self, request, *args, **kwargs):
        # 1. Validate Paystack HMAC signature
        signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
        if not signature:
            logger.warning("Paystack webhook received without signature header.")
            return Response({"error": "Missing signature"}, status=status.HTTP_400_BAD_REQUEST)

        secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
        computed_signature = hmac.new(
            secret,
            request.body,
            hashlib.sha512
        ).hexdigest()

        if not hmac.compare_digest(computed_signature, signature):
            logger.error("Paystack webhook signature verification failed.")
            return Response({"error": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        event = data.get('event')
        payload_data = data.get('data', {})
        metadata = payload_data.get('metadata', {})
        reference = payload_data.get('reference')
        bought_ticket_id = metadata.get('bought_ticket_id')

        # 2. Idempotency handling
        if event == 'charge.success':
            if reference and Payment.objects.filter(payment_id=reference).exists():
                logger.info(f"Payment {reference} already processed. Acknowledging webhook.")
                return Response(status=status.HTTP_200_OK)

            if bought_ticket_id:
                order = OrderTicket.objects.filter(id=bought_ticket_id, status='completed').first()
                if order:
                    logger.info(f"Order {bought_ticket_id} already marked completed. Acknowledging webhook.")
                    return Response(status=status.HTTP_200_OK)

            user_id = metadata.get('user_id')
            price = metadata.get('price')
            email = metadata.get('email')
            create_payment_record.delay(
                bought_ticket_id=bought_ticket_id,
                amount=price,
                user_id=user_id,
                email=email,
                paystack_ref=reference
            )

        elif event == 'charge.failed':
            user_id = metadata.get('user_id')
            price = metadata.get('price')
            email = metadata.get('email')
            payment_failed.delay(
                bought_ticket_id=bought_ticket_id,
                amount=price,
                user_id=user_id,
                email=email
            )

        return Response(status=status.HTTP_200_OK)


class TicketVerifyView(APIView):
    """
    Read-only ticket verification endpoint.
    Safe for camera scanners and previewing ticket details without altering ticket state.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        token = request.data.get('token')
        event_id = request.data.get('event_id')

        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

        ticket_query = SoldTicket.objects.select_related('ticket__event', 'user').filter(
            models.Q(qr_code_token=token) | models.Q(ticket_number=token) | models.Q(key=str(token))
        )
        if event_id:
            ticket_query = ticket_query.filter(ticket__event__id=event_id)

        ticket = ticket_query.first()
        if not ticket:
            return Response({
                'valid': False,
                'status': 'INVALID',
                'message': 'Ticket not found or does not belong to this event.'
            }, status=status.HTTP_404_NOT_FOUND)

        is_valid = (ticket.status == TicketStatus.ISSUED and not ticket.used)
        event_obj = ticket.ticket.event if ticket.ticket else None

        return Response({
            'valid': is_valid,
            'status': ticket.status,
            'ticket_number': ticket.ticket_number or ticket.key,
            'label': ticket.ticket.label if ticket.ticket else None,
            'attendee_name': ticket.user.fullname if ticket.user else 'Guest',
            'attendee_email': ticket.user.email if ticket.user else None,
            'checked_in_at': ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
            'check_in_gate': ticket.check_in_gate or None,
            'event': {
                'id': str(event_obj.id) if event_obj else None,
                'name': event_obj.name if event_obj else None,
            } if event_obj else None
        }, status=status.HTTP_200_OK)


class TicketCheckInView(APIView):
    """
    State-mutating ticket check-in endpoint.
    Uses atomic conditional SQL update to prevent concurrent double check-ins.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        token = request.data.get('token')
        event_id = request.data.get('event_id')
        gate = request.data.get('gate', 'Main Gate')
        device_info = request.data.get('device_info', '')

        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()

        # 1. Fetch ticket to check existence
        ticket_query = SoldTicket.objects.select_related('ticket__event', 'user').filter(
            models.Q(qr_code_token=token) | models.Q(ticket_number=token) | models.Q(key=str(token))
        )
        if event_id:
            ticket_query = ticket_query.filter(ticket__event__id=event_id)

        ticket = ticket_query.first()
        event_obj = ticket.ticket.event if (ticket and ticket.ticket) else None

        if not ticket:
            CheckInLog.objects.create(
                scanned_token=token,
                event_id=event_id if event_id else None,
                scanned_by=request.user,
                gate=gate,
                device_info=device_info,
                result=CheckInResult.INVALID_TOKEN,
                notes="Token unrecognized or event mismatch"
            )
            return Response({
                'status': 'INVALID',
                'message': 'Ticket not found or does not belong to this event'
            }, status=status.HTTP_404_NOT_FOUND)

        # 2. Check for cancelled or refunded status
        if ticket.status == TicketStatus.CANCELLED:
            CheckInLog.objects.create(
                ticket=ticket,
                scanned_token=token,
                event=event_obj,
                scanned_by=request.user,
                gate=gate,
                device_info=device_info,
                result=CheckInResult.CANCELLED,
                notes="Ticket was cancelled"
            )
            return Response({
                'status': 'CANCELLED',
                'message': 'This ticket was cancelled prior to the event.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if ticket.status == TicketStatus.REFUNDED:
            CheckInLog.objects.create(
                ticket=ticket,
                scanned_token=token,
                event=event_obj,
                scanned_by=request.user,
                gate=gate,
                device_info=device_info,
                result=CheckInResult.REFUNDED,
                notes="Ticket was refunded"
            )
            return Response({
                'status': 'REFUNDED',
                'message': 'This ticket was refunded.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 3. ATOMIC CONDITIONAL UPDATE:
        # PostgreSQL locks the target row exclusively during UPDATE.
        # If two requests race:
        # First request updates 1 row (status goes from ISSUED -> CHECKED_IN).
        # Second request evaluates status=ISSUED against the committed row and updates 0 rows!
        with transaction.atomic():
            rows_updated = SoldTicket.objects.filter(
                id=ticket.id,
                status=TicketStatus.ISSUED,
                used=False
            ).update(
                status=TicketStatus.CHECKED_IN,
                used=True,
                checked_in_at=now,
                checked_in_by=request.user,
                check_in_gate=gate,
                updated_at=now
            )

            if rows_updated == 1:
                CheckInLog.objects.create(
                    ticket=ticket,
                    scanned_token=token,
                    event=event_obj,
                    scanned_by=request.user,
                    gate=gate,
                    device_info=device_info,
                    result=CheckInResult.SUCCESS,
                    notes=f"Admitted via {gate}"
                )
                return Response({
                    'status': 'SUCCESS',
                    'message': 'Welcome! Ticket successfully checked in.',
                    'ticket': {
                        'ticket_number': ticket.ticket_number or ticket.key,
                        'tier': ticket.ticket.label if ticket.ticket else None,
                        'attendee_name': ticket.user.fullname if ticket.user else 'Guest',
                        'checked_in_at': now.isoformat(),
                        'gate': gate
                    }
                }, status=status.HTTP_200_OK)
            else:
                # Duplicate scan detected
                ticket.refresh_from_db()
                CheckInLog.objects.create(
                    ticket=ticket,
                    scanned_token=token,
                    event=event_obj,
                    scanned_by=request.user,
                    gate=gate,
                    device_info=device_info,
                    result=CheckInResult.ALREADY_USED,
                    notes=f"Duplicate scan attempted at {gate}"
                )
                return Response({
                    'status': 'ALREADY_CHECKED_IN',
                    'message': 'Warning: Ticket has already been checked in!',
                    'ticket': {
                        'ticket_number': ticket.ticket_number or ticket.key,
                        'tier': ticket.ticket.label if ticket.ticket else None,
                        'attendee_name': ticket.user.fullname if ticket.user else 'Guest',
                        'original_checkin_time': ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
                        'original_gate': ticket.check_in_gate,
                        'scanned_by': ticket.checked_in_by.fullname if ticket.checked_in_by else 'Staff'
                    }
                }, status=status.HTTP_409_CONFLICT)


class VerifyQrcode(APIView):
    """
    Legacy read-only verification endpoint to ensure backward compatibility
    with existing QR codes in circulation.
    """
    permission_classes = []

    def get(self, *args, **kwargs):
        event = self.kwargs['event']
        key = str(self.kwargs['key'])
        try:
            ticket = SoldTicket.objects.select_related("ticket", "ticket__event").get(
                ticket__event__id=event,
                key=key
            )
            is_valid = (ticket.status == TicketStatus.ISSUED and not ticket.used)
            return Response({
                'valid': is_valid,
                'status': ticket.status,
                'ticket_number': ticket.ticket_number or ticket.key,
                'event': {
                    "id": str(ticket.ticket.event.id),
                    "name": ticket.ticket.event.name,
                    "label": ticket.ticket.label
                }
            })
        except Exception:
            return Response({'valid': False})
 


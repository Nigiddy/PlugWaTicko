from django.db import models
from Users.models import User
import uuid
from Events.models import OrderTicket, TicketPrice, Event


class TicketStatus(models.TextChoices):
    ISSUED = 'ISSUED', 'Issued'
    CHECKED_IN = 'CHECKED_IN', 'Checked In'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REFUNDED = 'REFUNDED', 'Refunded'
    EXPIRED = 'EXPIRED', 'Expired'


class CheckInResult(models.TextChoices):
    SUCCESS = 'SUCCESS', 'Check-in Successful'
    ALREADY_USED = 'ALREADY_USED', 'Already Checked In'
    INVALID_EVENT = 'INVALID_EVENT', 'Ticket Not Valid for This Event'
    CANCELLED = 'CANCELLED', 'Ticket Cancelled'
    REFUNDED = 'REFUNDED', 'Ticket Refunded'
    INVALID_TOKEN = 'INVALID_TOKEN', 'Token Unrecognized'


class Payment(models.Model):
    id=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    user=models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='user_payments')
    payment_id=models.CharField(max_length=100)
    amount=models.FloatField()
    ticket=models.OneToOneField(OrderTicket, on_delete=models.CASCADE, related_name='payment')
    date=models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.payment_id

    def get_event_owner_payment(self):
        return self.amount 


class SoldTicket(models.Model):
    id=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    payment=models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='sold_tickets')
    ticket=models.ForeignKey(TicketPrice, related_name='ticket', on_delete=models.SET_NULL, null=True)
    event=models.ForeignKey(OrderTicket, on_delete=models.SET_NULL, null=True, related_name='event_tickets')
    key=models.CharField(max_length=32, blank=True, null=True, db_index=True)
    user=models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='user_purchased_tickets')
    used=models.BooleanField(default=False)

    # State machine and unique identifiers
    status=models.CharField(max_length=20, choices=TicketStatus.choices, default=TicketStatus.ISSUED, db_index=True)
    ticket_number=models.CharField(max_length=32, unique=True, null=True, db_index=True)
    qr_code_token=models.CharField(max_length=64, unique=True, null=True, db_index=True)

    # Check-in audit metadata
    checked_in_at=models.DateTimeField(null=True, blank=True)
    checked_in_by=models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='scanned_tickets')
    check_in_gate=models.CharField(max_length=100, blank=True, default='')

    created_at=models.DateTimeField(auto_now_add=True, null=True)
    updated_at=models.DateTimeField(auto_now=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['ticket', 'status'], name='soldtkt_tkt_status_idx'),
            models.Index(fields=['qr_code_token', 'status'], name='soldtkt_qr_status_idx'),
            models.Index(fields=['ticket_number'], name='soldtkt_number_idx'),
        ]

    def __str__(self):
        return f"{self.ticket_number or self.key or self.id} ({self.status})"


class CheckInLog(models.Model):
    id=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    ticket=models.ForeignKey(SoldTicket, on_delete=models.CASCADE, related_name='check_in_logs', null=True, blank=True)
    scanned_token=models.CharField(max_length=64)
    event=models.ForeignKey(Event, on_delete=models.CASCADE, related_name='check_in_logs', null=True, blank=True)
    scanned_by=models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    scanned_at=models.DateTimeField(auto_now_add=True)
    gate=models.CharField(max_length=100, blank=True, default='Main Gate')
    device_info=models.CharField(max_length=255, blank=True, default='')
    result=models.CharField(max_length=25, choices=CheckInResult.choices)
    notes=models.TextField(blank=True, default='')

    class Meta:
        ordering=['-scanned_at']
        indexes = [
            models.Index(fields=['event', 'scanned_at'], name='checkin_evt_scan_idx'),
            models.Index(fields=['ticket', 'result'], name='checkin_tkt_res_idx'),
        ]

    def __str__(self):
        return f"{self.result} - {self.scanned_token[:8]} at {self.scanned_at}"


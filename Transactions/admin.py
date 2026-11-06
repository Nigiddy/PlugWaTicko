from django.contrib import admin
from .models import Payment, SoldTicket, CheckInLog, TicketStatus

def deactivate_tickets(modeladmin, request, queryset):
    queryset.update(status=TicketStatus.CANCELLED, used=True)
deactivate_tickets.short_description='cancel selected tickets'

class SoldTicketAdmin(admin.ModelAdmin):
    list_display=['ticket_number', 'user', 'ticket', 'status', 'used', 'checked_in_at', 'check_in_gate']
    list_filter=['status', 'used', 'check_in_gate']
    search_fields=['ticket_number', 'qr_code_token', 'key', 'user__email']
    actions=[deactivate_tickets]

class CheckInLogAdmin(admin.ModelAdmin):
    list_display=['result', 'ticket', 'event', 'scanned_by', 'gate', 'scanned_at']
    list_filter=['result', 'gate', 'scanned_at']
    search_fields=['scanned_token', 'ticket__ticket_number', 'event__name']

class PaymentAdmin(admin.ModelAdmin):
    list_display=['payment_id', 'user', 'amount', 'date', 'ticket']
    list_display_links=['payment_id', 'user', 'ticket']
    list_filter=['date']
    search_fields=['payment_id', 'user__email']

admin.site.register(SoldTicket, SoldTicketAdmin)
admin.site.register(CheckInLog, CheckInLogAdmin)
admin.site.register(Payment, PaymentAdmin)


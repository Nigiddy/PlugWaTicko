from django.db import models
from django.utils import timezone
from cloudinary.models import CloudinaryField
from Users.models import User
import uuid
from django.core.exceptions import ValidationError

class OrderStatus(models.TextChoices):
    PENDING = 'not completed', 'Pending'
    RESERVED = 'RESERVED', 'Inventory Reserved'
    COMPLETED = 'completed', 'Completed'
    EXPIRED = 'EXPIRED', 'Reservation Expired'
    CANCELLED = 'CANCELLED', 'Order Cancelled'

class Category(models.Model):
    name=models.CharField(max_length=50, unique=True, primary_key=True)

    class Meta:
        verbose_name_plural= "categories"
        ordering=["name"]
    def __str__(self): 
        return self.name
    
    def clean(self, *args, **kwargs):
        category=Category.objects.filter(name__iexact=self.name)
        if category.exists():
            raise ValidationError({'name':'category with this name already exists'})
        return category
    



class Event(models.Model):
    user=models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    id=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    name=models.CharField(max_length=500)
    country=models.CharField(max_length=300)
    category=models.ManyToManyField(Category, related_name= 'event_categories')
    city=models.CharField(max_length=300)
    state=models.CharField(max_length=300)
    address=models.CharField(max_length=400)
    tags=models.JSONField(default=list, blank=True)
    description=models.TextField()
    image=CloudinaryField('images', null=True, blank=True)
    approved=models.BooleanField(default=False)
    date_added=models.DateTimeField(auto_now_add=True)
    start_date=models.DateTimeField()
    end_date=models.DateTimeField()

    class Meta:
        ordering= ['-date_added']
        indexes=[models.Index(fields=['date_added', 'approved'])]

    def __str__(self):
        return self.name

    def total_tickets_sold(self)-> int:
        total=0
        for ticket in self.event_fees.all():
            total += ticket.sold
        return total
    
 


class TicketPrice(models.Model):
    label=models.CharField(max_length=50)
    price=models.FloatField(default=0)
    event=models.ForeignKey(Event, on_delete=models.CASCADE, related_name='event_fees')
    description=models.TextField()
    is_free=models.BooleanField(default=False)
    sold=models.PositiveIntegerField(default=0)
    reserved=models.PositiveIntegerField(default=0)
    qty=models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(sold__lte=models.F('qty')),
                name='ticketprice_sold_lte_qty'
            ),
            models.CheckConstraint(
                check=models.Q(sold + models.F('reserved') <= models.F('qty')),
                name='ticketprice_sold_plus_reserved_lte_qty'
            ),
            models.CheckConstraint(
                check=models.Q(reserved__gte=0),
                name='ticketprice_reserved_gte_zero'
            ),
        ]

    def save(self, *args, **kwargs):
        if self.is_free:
            self.price= 0
        return super().save(*args, **kwargs)

    
    def get_tickets_available(self):
        return max(0, self.qty - self.sold - self.reserved)

    def __str__(self)->str:
        return f"{self.event} ({self.label})"


class BuyTicket(models.Model):
    id=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    user=models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_tickets', null=True)
    event_ticket=models.ForeignKey(TicketPrice, on_delete=models.SET_NULL, null=True)
    qty=models.PositiveIntegerField(default=1)
    emails=models.JSONField(default=list, blank=True)
    order=models.ForeignKey('OrderTicket', on_delete=models.CASCADE, related_name='tickets')
    date=models.DateTimeField(auto_now_add=True)
    completed=models.BooleanField(default=False)


    def get_total_ticket_price(self):
        return self.event_ticket.price * self.qty





class OrderTicket(models.Model):
    id=models.UUIDField(default=uuid.uuid4,editable=False, primary_key=True )
    event=models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, related_name='event_orders')
    user=models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_orders', null=True)
    status=models.CharField(choices=OrderStatus.choices, max_length=20, default=OrderStatus.PENDING, db_index=True)
    reservation_expires_at=models.DateTimeField(null=True, blank=True, db_index=True)
    paystack_reference=models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    date=models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['-date']
        indexes = [
            models.Index(fields=['status', 'reservation_expires_at']),
        ]
    
    def __str__(self):
        return str(self.user)

    def is_expired(self):
        return bool(self.reservation_expires_at and timezone.now() > self.reservation_expires_at)

    def get_total_price(self):
        total=0
        for i in self.tickets.all():
            total += i.get_total_ticket_price()
        return total




class TrendingEvents(models.Model):
    events=models.ManyToManyField(Event, related_name='events')


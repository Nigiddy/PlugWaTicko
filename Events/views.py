from .permissions import IsAdmin, IsAdminorReadOnly, IsOwner
from .serializers import BuyTicketSerializer,  CategorySerializer, EventCreateSerializer, EventSerializer, CreateEventPriceSerializer, TrendingEventSerializer
from rest_framework import generics, permissions, status, filters
from .models import Category, Event, BuyTicket, OrderTicket, TicketPrice, TrendingEvents, OrderStatus
from rest_framework.views import APIView
from rest_framework.response import Response
from django.urls import reverse
from django.db import transaction, models
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
import pytz
from datetime import datetime, timedelta



class EventView(generics.ListAPIView):
    '''
    List all events that has been be approved by the admin
    
    '''
    serializer_class=EventSerializer
    permission_classes=[]
    filter_backends=[DjangoFilterBackend]
    filterset_fields=['category', 'country']
    search_fields=['name', 'city', 'category__name', 'country']


    def get_queryset(self):
        return Event.objects.filter(approved=True, end_date__gt=datetime.now(tz=pytz.timezone('UTC'))-timedelta(minutes=30)).select_related('user').prefetch_related('event_fees')


class EventCreateView(generics.CreateAPIView):
    '''
    endpoint to create an event 
    
    '''
    serializer_class=EventCreateSerializer
    queryset=Event.objects.all()

    def perform_create(self, serializer):
        return serializer.save(user=self.request.user)

class CreateEventTicketPrice(generics.CreateAPIView):
    '''
   endpoint  to create  tickets for a particular event
   Note: only the owner of a event can create the prices
    '''
    serializer_class=CreateEventPriceSerializer
    queryset=TicketPrice.objects.all()

    
class EventDetailView(generics.RetrieveUpdateDestroyAPIView):
    '''
    endpoint to get all details of a particular Event
    '''
    serializer_class=EventCreateSerializer
    permission_classes=[IsOwner]


    
    def get_queryset(self):
        return Event.objects.all().select_related('user').prefetch_related('event_fees', 'category')

class RemoveTicketView(APIView):
    def post(self, *args, **kwargs):
        pk = self.kwargs["pk"]
        try:
            with transaction.atomic():
                ticket = TicketPrice.objects.select_for_update().get(id=pk)
                order = OrderTicket.objects.filter(
                    user=self.request.user,
                    status__in=['not completed', OrderStatus.RESERVED],
                    event=ticket.event
                ).last()
                if not order:
                    return Response({"message": "ticket doesn't exist or ticket not added"}, status=status.HTTP_400_BAD_REQUEST)

                buy_tickets = BuyTicket.objects.filter(event_ticket=ticket, completed=False, order=order)
                if not buy_tickets.exists():
                    return Response({"message": "ticket doesn't exist or ticket not added"}, status=status.HTTP_400_BAD_REQUEST)

                # Atomically release reserved inventory
                total_qty = sum(bt.qty for bt in buy_tickets)
                TicketPrice.objects.filter(id=ticket.id).update(
                    reserved=models.Case(
                        models.When(reserved__gte=total_qty, then=models.F('reserved') - total_qty),
                        default=0
                    )
                )
                buy_tickets.delete()
                return Response({"message": "success"}, status=status.HTTP_204_NO_CONTENT)
        except Exception:
            return Response({"message": "ticket doesn't exist or ticket not added"}, status=status.HTTP_400_BAD_REQUEST)


class BuyTicketView(APIView):
    serializer_class = BuyTicketSerializer

    def get_serializer(self):
        return BuyTicketSerializer()

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid(raise_exception=True):
            user = self.request.user
            ticket_id = self.kwargs["ticket_id"]
            qty = serializer.validated_data.get('qty')
            emails = serializer.validated_data.get('emails')

            try:
                with transaction.atomic():
                    # 1. Lock the TicketPrice tier row exclusively to guarantee overselling protection
                    ticket = TicketPrice.objects.select_for_update().get(id=ticket_id)

                    # 2. Find or create the active reservation order for this event
                    order = OrderTicket.objects.filter(
                        user=user,
                        status__in=['not completed', OrderStatus.RESERVED],
                        event=ticket.event
                    ).last()

                    if not order:
                        order = OrderTicket.objects.create(
                            user=user,
                            status=OrderStatus.RESERVED,
                            event=ticket.event,
                            reservation_expires_at=timezone.now() + timedelta(minutes=15)
                        )

                    # 3. Check existing reserved quantity for this tier in cart
                    existing_buy = BuyTicket.objects.filter(user=user, event_ticket=ticket, completed=False, order=order).first()
                    prev_qty = existing_buy.qty if existing_buy else 0
                    diff_qty = qty - prev_qty

                    # 4. Check availability
                    available = ticket.get_tickets_available()
                    if diff_qty > 0 and available < diff_qty:
                        if available == 0:
                            return Response({'error': 'tickets sold out'}, status=status.HTTP_400_BAD_REQUEST)
                        return Response({
                            'error': 'tickets available not up to this qty',
                            'available': available
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # 5. Atomically adjust the reserved counter
                    if diff_qty != 0:
                        TicketPrice.objects.filter(id=ticket.id).update(
                            reserved=models.Case(
                                models.When(reserved__gte=-diff_qty, then=models.F('reserved') + diff_qty),
                                default=0
                            ) if diff_qty < 0 else models.F('reserved') + diff_qty
                        )

                    # 6. Save or update BuyTicket
                    if existing_buy:
                        existing_buy.qty = qty
                        existing_buy.emails = emails
                        existing_buy.save()
                    else:
                        BuyTicket.objects.create(user=user, event_ticket=ticket, qty=qty, emails=emails, order=order)

                    # 7. Set 15-minute reservation expiry window
                    reservation_ttl = timezone.now() + timedelta(minutes=15)
                    order.status = OrderStatus.RESERVED
                    order.reservation_expires_at = reservation_ttl
                    order.save(update_fields=['status', 'reservation_expires_at'])

                    return Response({
                        "payment-link": reverse('payment', kwargs={'pk': order.id}),
                        "amount_to_pay": order.get_total_price(),
                        "reservation_expires_at": reservation_ttl.isoformat(),
                        "expires_in_seconds": 900
                    }, status=status.HTTP_201_CREATED)

            except TicketPrice.DoesNotExist:
                return Response({'error': 'This ticket cant be found'}, status=status.HTTP_404_NOT_FOUND)






class CategoryView(generics.ListCreateAPIView):
    '''
    (GET: endpoint to list all the categories of events)
    (POST: endpoint to create a category)
    '''

    queryset=Category.objects.all()
    serializer_class=CategorySerializer
    permission_classes=[IsAdminorReadOnly]

class TrendingEventss(generics.ListAPIView):
    '''
    endpoint to list all trending events
    '''
    serializer_class=EventSerializer
    permission_classes=[]

    def get_queryset(self):
        try:
  
           return TrendingEvents.objects.prefetch_related('events').last().events.all().select_related('user').prefetch_related('event_fees')
        except:
            return [] 

class TrendingEventView(generics.UpdateAPIView):
    '''
    endpoint to update the trending events, just input the id of the events you want to be trending
    '''
    serializer_class=TrendingEventSerializer
    permission_classes=[permissions.IsAuthenticated, IsAdmin]
    


    def get_object(self):
        return TrendingEvents.objects.prefetch_related('events').last()








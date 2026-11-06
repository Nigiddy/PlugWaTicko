from django.urls import path 
from . import views

urlpatterns = [ 
    path('make-payment/<uuid:pk>/', views.Makepayment.as_view(), name='payment'),
    path('paystack-webhook/', views.PayStack_Webhook.as_view(), name='paystack-webhook'),
    path('tickets/verify/', views.TicketVerifyView.as_view(), name='ticket-verify'),
    path('tickets/check-in/', views.TicketCheckInView.as_view(), name='ticket-check-in'),
    path('verify-qrcode/<uuid:event>/<str:key>/', views.VerifyQrcode.as_view(), name='verify-qrcode'),
]

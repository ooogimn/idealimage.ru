from django.contrib import admin
from django.urls import path, include
from .views import *

app_name = 'Home'

urlpatterns = [
    path('search/', SearchPageView.as_view(), name='search_page'),
    path('documents/', documents, name='documents'),
    path('documents/agreement/', agreement, name='agreement'),
    path('documents/privacy/', privacy, name='privacy'),
    path('documents/cookie/', cookie_policy, name='cookie_policy'),
    path('documents/offer/', offer, name='offer'),
    path('documents/requisites/', requisites, name='requisites'),
    path('help/', help_page, name='help'),
    path('advertise/', advertising, name='advertising'),  # Переименовано чтобы не конфликтовать с /advertising/ (панель управления)
    
    # Лендинг №2
    path('landing2/', landing_2, name='landing2'),
    path('api/booking/submit/', booking_submit, name='booking_submit'),
    
    # Главная панель администратора
    path('dashboard/', master_admin_dashboard, name='master_admin_dashboard'),
    
    path('', home, name='home'),
]


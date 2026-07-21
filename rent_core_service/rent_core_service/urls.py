"""
URL configuration for rent_core_service project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.http import JsonResponse

def ping(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path('api/ping/', ping, name='ping'),
    path('api/users/', include('Users.urls')),
    path('api/properties/', include('Properties.urls')),
    path('api/address/', include('Address.urls')),
    path('api/bookings/', include('Bookings.urls')),
    path('api/maintenance/', include('Maintenance.urls')),
    path('api/rent/', include('Rent.urls')),
    path('api/invoices/', include('Invoices.urls')),
    path('api/transactions/', include('Transactions.urls')),
    path('api/notifications/', include('Notifications.urls')),
    path('api/padvault-hq/', include('Admin.urls')),

]

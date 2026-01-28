"""
URLs para la app core - Autenticación y API
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Router para ViewSets
router = DefaultRouter()
router.register(r'clients', views.ClientViewSet, basename='client')
router.register(r'shipments', views.ShipmentViewSet, basename='shipment')

urlpatterns = [
    # Autenticación
    path('auth/login/', views.login_view, name='login'),
    path('auth/refresh/', views.refresh_token_view, name='token_refresh'),
    path('auth/me/', views.me_view, name='me'),
    path('auth/logout/', views.logout_view, name='logout'),
    
    # Maestro de Materiales (FASE 1)
    path('materials/', views.material_master_list, name='material-master'),
    
    # Firma de Sales Confirmation - Magic Link (FASE 1)
    path('sign/<int:shipment_id>/<str:token>/', views.view_sales_confirmation, name='view-sc'),
    path('sign/<int:shipment_id>/<str:token>/submit/', views.sign_sales_confirmation, name='sign-sc'),
    
    # ViewSets
    path('', include(router.urls)),
]

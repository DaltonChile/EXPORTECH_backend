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
    # Autenticación (Exportadores)
    path('auth/login/', views.login_view, name='login'),
    path('auth/refresh/', views.refresh_token_view, name='token_refresh'),
    path('auth/me/', views.me_view, name='me'),
    path('auth/logout/', views.logout_view, name='logout'),
    
    # Maestro de Materiales (FASE 1)
    path('materials/', views.material_master_list, name='material-master'),
    
    # Firma de Sales Confirmation - Magic Link (FASE 1)
    path('sign/<int:shipment_id>/<str:token>/', views.view_sales_confirmation, name='view-sc'),
    path('sign/<int:shipment_id>/<str:token>/submit/', views.sign_sales_confirmation, name='sign-sc'),
    
    # Platform Admin (Dueños de la plataforma) - Sistema separado
    path('platform/login/', views.platform_login, name='platform-login'),
    path('platform/me/', views.platform_me, name='platform-me'),
    path('platform/stats/', views.platform_stats, name='platform-stats'),
    path('platform/organizations/', views.platform_organizations, name='platform-organizations'),
    path('platform/organizations/<int:org_id>/', views.platform_organization_detail, name='platform-organization-detail'),
    path('platform/users/', views.platform_users, name='platform-users'),
    path('platform/users/<int:user_id>/', views.platform_user_detail, name='platform-user-detail'),
    
    # ViewSets
    path('', include(router.urls)),
]

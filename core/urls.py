"""
URLs - Arquitectura Multi-Tenant
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Router para ViewSets
router = DefaultRouter()
router.register(r'clients', views.ClientViewSet, basename='client')
router.register(r'shipments', views.ShipmentViewSet, basename='shipment')

urlpatterns = [
    # ============================================
    # AUTH (Usuarios normales)
    # ============================================
    path('auth/login/', views.login, name='login'),
    path('auth/me/', views.me, name='me'),
    
    # Claim Account (Shadow Org → Active)
    path('auth/claim/verify/<str:token>/', views.verify_claim_token, name='verify-claim'),
    path('auth/claim/<str:token>/', views.claim_account, name='claim-account'),
    
    # ============================================
    # RESOURCES
    # ============================================
    path('materials/', views.materials_list, name='materials'),
    path('importer/dashboard/', views.importer_dashboard, name='importer-dashboard'),
    
    # ============================================
    # MAGIC LINK / FIRMA PÚBLICA
    # ============================================
    path('sign/<int:shipment_id>/<str:token>/', views.view_sales_confirmation, name='view-sc'),
    path('sign/<int:shipment_id>/<str:token>/submit/', views.sign_sales_confirmation, name='sign-sc'),
    
    # ============================================
    # PLATFORM ADMIN
    # ============================================
    path('platform/login/', views.platform_login, name='platform-login'),
    path('platform/stats/', views.platform_stats, name='platform-stats'),
    path('platform/organizations/', views.platform_organizations, name='platform-organizations'),
    path('platform/organizations/<uuid:org_id>/', views.platform_organization_detail, name='platform-organization-detail'),
    path('platform/users/', views.platform_users, name='platform-users'),
    path('platform/users/<uuid:user_id>/', views.platform_user_detail, name='platform-user-detail'),
    path('platform/config/', views.platform_system_config, name='platform-config'),
    
    # ============================================
    # VIEWSETS
    # ============================================
    path('', include(router.urls)),
]

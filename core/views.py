"""
Views - Arquitectura Multi-Tenant
"""
import os
import secrets
import threading
import jwt
from datetime import datetime, timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.mail import send_mail

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    SystemConfig, Organization, User, BusinessRelation,
    Shipment, ShipmentParticipant, SalesItem, MagicLink, SignatureLog
)
from .serializers import (
    SystemConfigSerializer,
    OrganizationSerializer, OrganizationMinimalSerializer, CreatePartnerOrganizationSerializer,
    UserSerializer,
    BusinessRelationSerializer, ClientListSerializer,
    ShipmentListSerializer, ShipmentDetailSerializer, ShipmentCreateSerializer,
    SalesItemSerializer, SalesConfirmationSerializer, SignSalesConfirmationSerializer,
    PlatformLoginSerializer, OrganizationPlatformSerializer, UserPlatformSerializer,
    MATERIAL_MASTER, MaterialMasterSerializer
)
from .authentication import platform_admin_required, get_user_organization


# ============================================
# AUTH ENDPOINTS
# ============================================

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Login unificado para todos los usuarios
    POST /api/auth/login/
    Retorna el tipo de usuario para que el frontend redirija
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response(
            {'error': 'Email y password requeridos'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user = User.objects.get(email=email, is_active=True)
        
        if not user.check_password(password):
            return Response(
                {'error': 'Credenciales inválidas'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Generar tokens JWT
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })
        
    except User.DoesNotExist:
        return Response(
            {'error': 'Credenciales inválidas'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """
    Obtener datos del usuario actual
    GET /api/auth/me/
    """
    return Response(UserSerializer(request.user).data)


# ============================================
# CLIENTS (BUSINESS RELATIONS / AGENDA)
# ============================================

class ClientViewSet(viewsets.ViewSet):
    """
    Gestión de clientes (partners en la agenda)
    
    GET    /api/clients/          - Lista clientes de mi agenda
    POST   /api/clients/          - Crear cliente (Shadow Organization)
    GET    /api/clients/{id}/     - Detalle de cliente
    """
    permission_classes = [IsAuthenticated]
    
    def list(self, request):
        """Listar clientes de la agenda del usuario"""
        org = get_user_organization(request.user)
        if not org:
            return Response({'error': 'Usuario sin organización'}, status=400)
        
        relations = BusinessRelation.objects.filter(
            host_org=org
        ).select_related('partner_org').order_by('-created_at')
        
        serializer = ClientListSerializer(relations, many=True)
        return Response(serializer.data)
    
    def create(self, request):
        """Crear nuevo cliente (Shadow Organization con status UNCLAIMED)"""
        serializer = CreatePartnerOrganizationSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            partner_org = serializer.save()
            return Response({
                'id': str(partner_org.id),
                'name': partner_org.name,
                'message': 'Cliente creado exitosamente'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def retrieve(self, request, pk=None):
        """Detalle de un cliente"""
        org = get_user_organization(request.user)
        if not org:
            return Response({'error': 'Usuario sin organización'}, status=400)
        
        relation = get_object_or_404(
            BusinessRelation,
            host_org=org,
            partner_org_id=pk
        )
        
        return Response({
            'organization': OrganizationSerializer(relation.partner_org).data,
            'alias': relation.alias,
            'notes': relation.notes,
        })


# ============================================
# SHIPMENTS
# ============================================

class ShipmentViewSet(viewsets.ModelViewSet):
    """
    Gestión de embarques
    
    GET    /api/shipments/                     - Lista embarques
    POST   /api/shipments/                     - Crear embarque
    GET    /api/shipments/{id}/                - Detalle embarque
    GET    /api/shipments/{id}/sales-confirmation/  - Datos para SC
    POST   /api/shipments/{id}/send-sc/        - Enviar SC al cliente
    POST   /api/shipments/{id}/add-item/       - Agregar ítem
    PUT    /api/shipments/{id}/update-item/{item_id}/  - Actualizar ítem
    DELETE /api/shipments/{id}/delete-item/{item_id}/  - Eliminar ítem
    """
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtrar embarques según organización:
        - Si es owner_org: ve todos sus embarques
        - Si es participant: ve embarques donde participa
        - Platform admin: ve todo
        """
        user = self.request.user
        
        if getattr(user, 'is_platform_admin', False):
            return Shipment.objects.all()
        
        org = user.organization
        if not org:
            return Shipment.objects.none()
        
        # Embarques propios + donde participa
        from django.db.models import Q
        return Shipment.objects.filter(
            Q(owner_org=org) | 
            Q(participants__organization=org)
        ).distinct().select_related('owner_org', 'created_by').order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ShipmentCreateSerializer
        if self.action == 'retrieve':
            return ShipmentDetailSerializer
        return ShipmentListSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = ShipmentCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            shipment = serializer.save()
            return Response(
                ShipmentDetailSerializer(shipment).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='sales-confirmation')
    def sales_confirmation(self, request, pk=None):
        """Obtener datos del Sales Confirmation para PDF"""
        shipment = self.get_object()
        serializer = SalesConfirmationSerializer(shipment)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='send-sc')
    def send_sales_confirmation(self, request, pk=None):
        """Enviar Sales Confirmation al cliente por email"""
        shipment = self.get_object()
        
        if shipment.status not in ['DRAFT', 'SC_SENT']:
            return Response(
                {'error': 'Solo se puede enviar SC en estado DRAFT'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener email del buyer
        buyer = shipment.participants.filter(role_type='BUYER').first()
        if not buyer:
            return Response(
                {'error': 'No hay comprador asignado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        client_email = buyer.organization.contact_email
        if not client_email:
            return Response(
                {'error': 'El cliente no tiene email configurado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Invalidar magic links anteriores
        MagicLink.objects.filter(shipment=shipment, is_active=True).update(is_active=False)
        
        # Generar nuevo magic link
        magic_token = secrets.token_urlsafe(32)
        magic_link = MagicLink.objects.create(
            shipment=shipment,
            token=magic_token,
            email_sent_to=client_email,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        frontend_url = os.environ.get('FRONTEND_URL', 'http://localhost:5173')
        magic_url = f"{frontend_url}/sign/{shipment.id}/{magic_token}"
        
        # Email HTML
        seller = shipment.participants.filter(role_type='SELLER').first()
        seller_name = seller.organization.name if seller else 'Exportador'
        
        html_message = f'''
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px; border-radius: 12px 12px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">Sales Confirmation</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 5px 0 0 0;">Ref: {shipment.internal_ref}</p>
                </div>
                <div style="background: #f8fafc; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
                    <p>Estimado cliente,</p>
                    <p>Le enviamos la Sales Confirmation para su revisión y aprobación.</p>
                    <p><strong>Vendedor:</strong> {seller_name}</p>
                    <p><strong>Incoterm:</strong> {shipment.incoterm} {shipment.destination_port}</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{magic_url}" style="display: inline-block; background: #2563eb; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold;">
                            Revisar y Firmar
                        </a>
                    </div>
                    <p style="color: #64748b; font-size: 14px;">Este enlace expira en 7 días.</p>
                </div>
            </div>
        </body>
        </html>
        '''
        
        # Enviar email en background
        def send_email_async():
            try:
                send_mail(
                    subject=f'Action Required: Sign Sales Confirmation #{shipment.internal_ref}',
                    message=f'Please review and sign: {magic_url}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[client_email],
                    html_message=html_message,
                    fail_silently=False,
                )
                print(f"✅ Email enviado a {client_email}")
            except Exception as e:
                print(f"❌ Error enviando email: {e}")
        
        email_thread = threading.Thread(target=send_email_async)
        email_thread.start()
        
        # Actualizar estado
        shipment.status = 'SC_SENT'
        shipment.save()
        
        return Response({
            'message': f'Sales Confirmation enviándose a {client_email}',
            'magic_link': magic_url,
            'expires_at': magic_link.expires_at.isoformat()
        })
    
    @action(detail=True, methods=['post'], url_path='add-item')
    def add_sales_item(self, request, pk=None):
        """Agregar ítem al embarque"""
        shipment = self.get_object()
        
        if shipment.status not in ['DRAFT', 'SC_SENT']:
            return Response(
                {'error': 'No se puede modificar este embarque'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = SalesItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(shipment=shipment)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['put'], url_path='update-item/(?P<item_id>[^/.]+)')
    def update_sales_item(self, request, pk=None, item_id=None):
        """Actualizar ítem del embarque"""
        shipment = self.get_object()
        
        if shipment.status not in ['DRAFT', 'SC_SENT']:
            return Response(
                {'error': 'No se puede modificar este embarque'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            item = SalesItem.objects.get(id=item_id, shipment=shipment)
        except SalesItem.DoesNotExist:
            return Response({'error': 'Ítem no encontrado'}, status=404)
        
        if 'price' in request.data:
            item.price = request.data['price']
        if 'quantity' in request.data:
            item.quantity = request.data['quantity']
        if 'description' in request.data:
            item.description = request.data['description']
        
        item.save()
        return Response(SalesItemSerializer(item).data)
    
    @action(detail=True, methods=['delete'], url_path='delete-item/(?P<item_id>[^/.]+)')
    def delete_sales_item(self, request, pk=None, item_id=None):
        """Eliminar ítem del embarque"""
        shipment = self.get_object()
        
        if shipment.status not in ['DRAFT', 'SC_SENT']:
            return Response(
                {'error': 'No se puede modificar este embarque'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            item = SalesItem.objects.get(id=item_id, shipment=shipment)
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except SalesItem.DoesNotExist:
            return Response({'error': 'Ítem no encontrado'}, status=404)


# ============================================
# MAGIC LINK / FIRMA PÚBLICA
# ============================================

@api_view(['GET'])
@permission_classes([AllowAny])
def view_sales_confirmation(request, shipment_id, token):
    """
    Vista pública del Sales Confirmation via magic link
    GET /api/sign/{shipment_id}/{token}/
    """
    magic_link = get_object_or_404(MagicLink, shipment_id=shipment_id, token=token)
    
    if not magic_link.is_valid():
        return Response(
            {'error': 'Este enlace ha expirado o ya fue utilizado'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    shipment = magic_link.shipment
    serializer = SalesConfirmationSerializer(shipment)
    
    return Response({
        'shipment': serializer.data,
        'can_sign': shipment.status in ['DRAFT', 'SC_SENT'],
        'expires_at': magic_link.expires_at.isoformat()
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def sign_sales_confirmation(request, shipment_id, token):
    """
    Firmar o rechazar Sales Confirmation
    POST /api/sign/{shipment_id}/{token}/submit/
    """
    magic_link = get_object_or_404(MagicLink, shipment_id=shipment_id, token=token)
    
    if not magic_link.is_valid():
        return Response(
            {'error': 'Este enlace ha expirado o ya fue utilizado'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    shipment = magic_link.shipment
    
    if shipment.status not in ['DRAFT', 'SC_SENT']:
        return Response(
            {'error': 'Este documento ya fue procesado'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    serializer = SignSalesConfirmationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    client_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    # Marcar magic link como usado
    magic_link.used_at = timezone.now()
    magic_link.is_active = False
    magic_link.save()
    
    if data['action'] == 'approve':
        SignatureLog.objects.create(
            shipment=shipment,
            magic_link=magic_link,
            status='APPROVED',
            signature_name=data['signature_name'],
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        shipment.status = 'SIGNED'
        shipment.save()
        
        return Response({
            'message': 'Sales Confirmation firmado exitosamente',
            'status': 'SIGNED',
            'signed_by': data['signature_name'],
        })
    
    else:  # reject
        SignatureLog.objects.create(
            shipment=shipment,
            magic_link=magic_link,
            status='REJECTED',
            rejection_comment=data['rejection_comment'],
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        # Volver a DRAFT para permitir correcciones
        shipment.status = 'DRAFT'
        shipment.save()
        
        return Response({
            'message': 'Sales Confirmation rechazado',
            'status': 'REJECTED',
            'rejection_comment': data['rejection_comment'],
        })


# ============================================
# MATERIALS
# ============================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def materials_list(request):
    """
    Obtener catálogo de materiales
    GET /api/materials/
    """
    serializer = MaterialMasterSerializer(MATERIAL_MASTER, many=True)
    return Response(serializer.data)


# ============================================
# PLATFORM ADMIN VIEWS
# ============================================

@api_view(['POST'])
@permission_classes([AllowAny])
def platform_login(request):
    """
    Login de Platform Admin
    POST /api/platform/login/
    """
    serializer = PlatformLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    
    try:
        user = User.objects.get(email=email, is_platform_admin=True, is_active=True)
        
        if not user.check_password(password):
            return Response({'error': 'Credenciales inválidas'}, status=401)
        
        # Actualizar last_login
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        # Generar JWT
        token = jwt.encode({
            'user_id': str(user.id),
            'email': user.email,
            'type': 'platform_admin',
            'exp': datetime.utcnow() + timedelta(hours=8)
        }, settings.SECRET_KEY, algorithm='HS256')
        
        return Response({
            'token': token,
            'user': {
                'id': str(user.id),
                'email': user.email,
                'name': user.name,
            }
        })
        
    except User.DoesNotExist:
        return Response({'error': 'Credenciales inválidas'}, status=401)


@platform_admin_required(['GET'])
def platform_dashboard(request):
    """
    Dashboard de Platform Admin
    GET /api/platform/dashboard/
    """
    return Response({
        'organizations_count': Organization.objects.count(),
        'users_count': User.objects.filter(is_platform_admin=False).count(),
        'shipments_count': Shipment.objects.count(),
        'exporters_count': Organization.objects.filter(type='EXPORTER').count(),
        'importers_count': Organization.objects.filter(type='IMPORTER').count(),
    })


@platform_admin_required(['GET', 'POST'])
def platform_organizations(request):
    """
    Gestión de organizaciones
    GET/POST /api/platform/organizations/
    """
    if request.method == 'GET':
        orgs = Organization.objects.all().order_by('-created_at')
        serializer = OrganizationPlatformSerializer(orgs, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = OrganizationSerializer(data=request.data)
        if serializer.is_valid():
            org = serializer.save()
            return Response(OrganizationPlatformSerializer(org).data, status=201)
        return Response(serializer.errors, status=400)


@platform_admin_required(['GET', 'PUT', 'DELETE'])
def platform_organization_detail(request, org_id):
    """
    Detalle de organización
    GET/PUT/DELETE /api/platform/organizations/{org_id}/
    """
    org = get_object_or_404(Organization, id=org_id)
    
    if request.method == 'GET':
        return Response(OrganizationPlatformSerializer(org).data)
    
    elif request.method == 'PUT':
        serializer = OrganizationSerializer(org, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(OrganizationPlatformSerializer(org).data)
        return Response(serializer.errors, status=400)
    
    elif request.method == 'DELETE':
        org.delete()
        return Response(status=204)


@platform_admin_required(['GET', 'POST'])
def platform_users(request):
    """
    Gestión de usuarios
    GET/POST /api/platform/users/
    """
    if request.method == 'GET':
        users = User.objects.filter(is_platform_admin=False).order_by('-created_at')
        serializer = UserPlatformSerializer(users, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = UserPlatformSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserPlatformSerializer(user).data, status=201)
        return Response(serializer.errors, status=400)


@platform_admin_required(['GET', 'PUT', 'DELETE'])
def platform_user_detail(request, user_id):
    """
    Detalle de usuario
    GET/PUT/DELETE /api/platform/users/{user_id}/
    """
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'GET':
        return Response(UserPlatformSerializer(user).data)
    
    elif request.method == 'PUT':
        serializer = UserPlatformSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(UserPlatformSerializer(user).data)
        return Response(serializer.errors, status=400)
    
    elif request.method == 'DELETE':
        user.delete()
        return Response(status=204)


@platform_admin_required(['GET', 'PUT'])
def platform_system_config(request):
    """
    Configuración del sistema
    GET/PUT /api/platform/config/
    """
    if request.method == 'GET':
        configs = SystemConfig.objects.all()
        return Response({c.key: c.value for c in configs})
    
    elif request.method == 'PUT':
        for key, value in request.data.items():
            SystemConfig.objects.update_or_create(
                key=key,
                defaults={'value': value}
            )
        return Response({'message': 'Configuración actualizada'})


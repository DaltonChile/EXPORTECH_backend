from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
import secrets

from .models import AppUser, ClientPartner, Shipment, SalesItem, MagicLink, SignatureLog
from .serializers import (
    ClientPartnerSerializer,
    ShipmentListSerializer, ShipmentDetailSerializer, ShipmentCreateSerializer,
    SalesConfirmationSerializer, SignSalesConfirmationSerializer,
    SalesItemSerializer, SalesItemCreateSerializer,
    MATERIAL_MASTER
)


@api_view(['POST'])
@permission_classes([AllowAny])  # Permite acceso sin autenticación
def login_view(request):
    """
    Vista de Login - Recibe email y password, retorna tokens JWT
    
    POST /api/auth/login/
    Body: { "email": "user@example.com", "password": "secret" }
    
    Respuesta exitosa:
    {
        "access": "eyJ0eXAiOiJKV1...",   # Token de acceso (8 horas)
        "refresh": "eyJ0eXAiOiJKV1...",  # Token de refresh (7 días)
        "user": {
            "id": 1,
            "email": "user@example.com",
            "role": "OPERADOR",
            "organization": "Salmones del Sur S.A."
        }
    }
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    # Validar que se enviaron los campos
    if not email or not password:
        return Response(
            {'error': 'Email y contraseña son requeridos'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Autenticar usuario
    user = authenticate(request, username=email, password=password)
    
    if user is None:
        return Response(
            {'error': 'Credenciales inválidas'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    if not user.is_active:
        return Response(
            {'error': 'Usuario desactivado'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    # Generar tokens JWT
    refresh = RefreshToken.for_user(user)
    
    # Preparar datos del usuario para el frontend
    user_data = {
        'id': user.id,
        'email': user.email,
        'role': user.role,
        'organization': user.organization.name if user.organization else None,
    }
    
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': user_data
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token_view(request):
    """
    Renueva el token de acceso usando el refresh token
    
    POST /api/auth/refresh/
    Body: { "refresh": "eyJ0eXAiOiJKV1..." }
    """
    refresh_token = request.data.get('refresh')
    
    if not refresh_token:
        return Response(
            {'error': 'Refresh token requerido'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        refresh = RefreshToken(refresh_token)
        return Response({
            'access': str(refresh.access_token),
        })
    except Exception:
        return Response(
            {'error': 'Refresh token inválido o expirado'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])  # Requiere autenticación
def me_view(request):
    """
    Retorna información del usuario autenticado
    Útil para verificar el token y obtener datos del usuario
    
    GET /api/auth/me/
    Headers: Authorization: Bearer <access_token>
    """
    user = request.user
    
    return Response({
        'id': user.id,
        'email': user.email,
        'role': user.role,
        'organization': user.organization.name if user.organization else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout - Invalida el refresh token
    
    POST /api/auth/logout/
    Body: { "refresh": "eyJ0eXAiOiJKV1..." }
    """
    refresh_token = request.data.get('refresh')
    
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()  # Invalida el token
        except Exception:
            pass  # Si falla, no importa
    
    return Response({'message': 'Logout exitoso'})


# ============================================
# FASE 1: ACUERDO COMERCIAL
# ============================================

# --- Maestro de Materiales ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def material_master_list(request):
    """
    Lista el Maestro de Materiales (productos disponibles)
    
    GET /api/materials/
    
    Retorna lista de SKUs con descripción para evitar errores de tipeo
    """
    return Response(MATERIAL_MASTER)


# --- Clientes ---
class ClientViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar clientes/importadores
    
    GET    /api/clients/         - Lista clientes
    POST   /api/clients/         - Crear cliente
    GET    /api/clients/{id}/    - Detalle cliente
    PUT    /api/clients/{id}/    - Actualizar cliente
    DELETE /api/clients/{id}/    - Eliminar cliente
    """
    serializer_class = ClientPartnerSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar por organización del usuario"""
        return ClientPartner.objects.filter(
            organization=self.request.user.organization
        ).order_by('-created_at')


# --- Embarques ---
class ShipmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar embarques
    
    GET    /api/shipments/              - Lista embarques
    POST   /api/shipments/              - Crear embarque (FASE 1)
    GET    /api/shipments/{id}/         - Detalle embarque
    PUT    /api/shipments/{id}/         - Actualizar embarque
    DELETE /api/shipments/{id}/         - Eliminar embarque
    
    Acciones adicionales:
    GET    /api/shipments/{id}/sales-confirmation/  - Ver Sales Confirmation
    POST   /api/shipments/{id}/send-sc/             - Enviar SC al cliente
    """
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar por organización del usuario"""
        return Shipment.objects.filter(
            organization=self.request.user.organization
        ).select_related('client', 'created_by').order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ShipmentCreateSerializer
        if self.action == 'retrieve':
            return ShipmentDetailSerializer
        return ShipmentListSerializer
    
    @action(detail=True, methods=['get'], url_path='sales-confirmation')
    def sales_confirmation(self, request, pk=None):
        """
        Obtener datos del Sales Confirmation para generar PDF
        
        GET /api/shipments/{id}/sales-confirmation/
        """
        shipment = self.get_object()
        serializer = SalesConfirmationSerializer(shipment)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='send-sc')
    def send_sales_confirmation(self, request, pk=None):
        """
        Enviar Sales Confirmation al cliente por email
        
        POST /api/shipments/{id}/send-sc/
        
        - Genera un magic link único
        - Guarda el token en BD con expiración
        - Envía email al cliente
        """
        shipment = self.get_object()
        
        if shipment.status != 'DRAFT':
            return Response(
                {'error': 'Solo se puede enviar SC en estado DRAFT'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar que el cliente tiene email
        client_email = shipment.client.contact_email
        if not client_email:
            return Response(
                {'error': 'El cliente no tiene email configurado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generar magic link token
        magic_token = secrets.token_urlsafe(32)
        
        # Crear MagicLink en BD con expiración de 7 días
        magic_link = MagicLink.objects.create(
            shipment=shipment,
            token=magic_token,
            email_sent_to=client_email,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        # Construir la URL del magic link (para el frontend en desarrollo)
        # En producción, cambiar a la URL real del frontend
        frontend_url = 'http://localhost:5173'
        magic_url = f"{frontend_url}/sign/{shipment.id}/{magic_token}"
        
        # Enviar email al cliente
        html_message = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px; border-radius: 12px 12px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">Sales Confirmation</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 5px 0 0 0;">Ref: {shipment.internal_ref}</p>
                </div>
                <div style="background: #f8fafc; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
                    <p>Estimado cliente,</p>
                    <p>Le enviamos la Sales Confirmation para su revisión y aprobación.</p>
                    <p><strong>Vendedor:</strong> {shipment.organization.name}</p>
                    <p><strong>Incoterm:</strong> {shipment.incoterm} {shipment.destination_port}</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{magic_url}" style="display: inline-block; background: #2563eb; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold;">
                            Revisar y Firmar
                        </a>
                    </div>
                    <p style="color: #64748b; font-size: 14px;">
                        Este enlace expira en 7 días. Si tiene preguntas, contacte a su representante.
                    </p>
                </div>
                <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                    <p>Exportech - Sistema de Gestión de Exportaciones</p>
                </div>
            </div>
        </body>
        </html>
        '''
        
        send_mail(
            subject=f'Action Required: Sign Sales Confirmation #{shipment.internal_ref}',
            message=f'Please review and sign the Sales Confirmation at: {magic_url}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[client_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return Response({
            'message': f'Sales Confirmation enviado a {client_email}',
            'magic_link': magic_url,  # Solo para desarrollo
            'shipment_ref': shipment.internal_ref,
            'expires_at': magic_link.expires_at.isoformat()
        })
    
    @action(detail=True, methods=['post'], url_path='add-item')
    def add_sales_item(self, request, pk=None):
        """
        Agregar ítem al embarque
        
        POST /api/shipments/{id}/add-item/
        Body: { "sku": "SKU-102", "description": "...", "price": 12.00, "quantity": 100 }
        """
        shipment = self.get_object()
        
        if shipment.status != 'DRAFT':
            return Response(
                {'error': 'No se puede modificar un embarque firmado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = SalesItemCreateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(shipment=shipment)
            return Response(SalesItemSerializer(serializer.instance).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])  # Sin autenticación - acceso via magic link
def view_sales_confirmation(request, shipment_id, token):
    """
    Vista pública para que el cliente vea la Sales Confirmation
    
    GET /api/sign/{shipment_id}/{token}/
    
    El cliente accede sin login via magic link
    """
    # Validar el magic link
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
        'can_sign': shipment.status == 'DRAFT',
        'expires_at': magic_link.expires_at.isoformat()
    })


@api_view(['POST'])
@permission_classes([AllowAny])  # Sin autenticación - acceso via magic link
def sign_sales_confirmation(request, shipment_id, token):
    """
    Firmar o rechazar Sales Confirmation
    
    POST /api/sign/{shipment_id}/{token}/submit/
    Body: 
    - Aprobar: { "action": "approve", "signature_name": "John Doe" }
    - Rechazar: { "action": "reject", "rejection_comment": "Precio incorrecto" }
    
    Captura IP y timestamp como prueba de conformidad
    """
    # Validar el magic link
    magic_link = get_object_or_404(MagicLink, shipment_id=shipment_id, token=token)
    
    if not magic_link.is_valid():
        return Response(
            {'error': 'Este enlace ha expirado o ya fue utilizado'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    shipment = magic_link.shipment
    
    if shipment.status != 'DRAFT':
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
        # Crear registro de firma
        signature_log = SignatureLog.objects.create(
            shipment=shipment,
            magic_link=magic_link,
            status='APPROVED',
            signature_name=data['signature_name'],
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        # Actualizar estado del embarque
        shipment.status = 'SIGNED'
        shipment.save()
        
        return Response({
            'message': 'Sales Confirmation firmado exitosamente',
            'status': 'SC_SIGNED',
            'signed_by': data['signature_name'],
            'signed_at': signature_log.signed_at.isoformat(),
            'ip_address': client_ip
        })
    
    else:  # reject
        # Crear registro de rechazo
        signature_log = SignatureLog.objects.create(
            shipment=shipment,
            magic_link=magic_link,
            status='REJECTED',
            rejection_comment=data['rejection_comment'],
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        # TODO: Notificar al exportador por email
        
        return Response({
            'message': 'Sales Confirmation rechazado',
            'status': 'SC_REJECTED',
            'rejection_comment': data['rejection_comment'],
            'rejected_at': signature_log.signed_at.isoformat(),
            'ip_address': client_ip
        })


# ============================================
# PLATFORM ADMIN VIEWS (Dueños de la plataforma)
# ============================================

from .models import PlatformAdmin, Organization
from .serializers import (
    PlatformAdminLoginSerializer,
    OrganizationPlatformSerializer, 
    AppUserPlatformSerializer
)
import jwt
from django.conf import settings as django_settings
from datetime import datetime, timedelta


def generate_platform_token(admin):
    """Genera un JWT para Platform Admin"""
    payload = {
        'platform_admin_id': admin.id,
        'email': admin.email,
        'type': 'platform_admin',
        'exp': datetime.utcnow() + timedelta(hours=24),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, django_settings.SECRET_KEY, algorithm='HS256')


def verify_platform_token(token):
    """Verifica y decodifica un token de Platform Admin"""
    try:
        payload = jwt.decode(token, django_settings.SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'platform_admin':
            return None
        return PlatformAdmin.objects.filter(id=payload['platform_admin_id'], is_active=True).first()
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def get_platform_admin_from_request(request):
    """Extrae el Platform Admin del header Authorization"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    return verify_platform_token(token)


@api_view(['POST'])
@permission_classes([AllowAny])
def platform_login(request):
    """
    Login para Platform Admins (dueños de la plataforma)
    
    POST /api/platform/login/
    Body: { "email": "admin@exportech.cl", "password": "secret" }
    """
    serializer = PlatformAdminLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    
    try:
        admin = PlatformAdmin.objects.get(email=email)
    except PlatformAdmin.DoesNotExist:
        return Response({'error': 'Credenciales inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
    
    if not admin.check_password(password):
        return Response({'error': 'Credenciales inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
    
    if not admin.is_active:
        return Response({'error': 'Cuenta desactivada'}, status=status.HTTP_401_UNAUTHORIZED)
    
    # Actualizar last_login
    admin.last_login = timezone.now()
    admin.save(update_fields=['last_login'])
    
    # Generar token
    token = generate_platform_token(admin)
    
    return Response({
        'token': token,
        'admin': {
            'id': admin.id,
            'email': admin.email,
            'name': admin.name,
        }
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def platform_me(request):
    """
    Obtener datos del Platform Admin actual
    
    GET /api/platform/me/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    return Response({
        'id': admin.id,
        'email': admin.email,
        'name': admin.name,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def platform_stats(request):
    """
    Estadísticas de la plataforma para Platform Admin
    
    GET /api/platform/stats/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    return Response({
        'organizations': Organization.objects.count(),
        'organizations_active': Organization.objects.filter(is_active=True).count(),
        'users': AppUser.objects.count(),
        'users_active': AppUser.objects.filter(is_active=True).count(),
        'shipments': Shipment.objects.count(),
        'clients': ClientPartner.objects.count(),
    })


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def platform_organizations(request):
    """
    Listar o crear organizaciones
    
    GET /api/platform/organizations/
    POST /api/platform/organizations/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    if request.method == 'GET':
        orgs = Organization.objects.all().order_by('-created_at')
        serializer = OrganizationPlatformSerializer(orgs, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = OrganizationPlatformSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def platform_organization_detail(request, org_id):
    """
    Detalle, actualizar o eliminar organización
    
    GET/PUT/DELETE /api/platform/organizations/{id}/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    org = get_object_or_404(Organization, id=org_id)
    
    if request.method == 'GET':
        serializer = OrganizationPlatformSerializer(org)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = OrganizationPlatformSerializer(org, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        org.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def platform_users(request):
    """
    Listar o crear usuarios de organizaciones
    
    GET /api/platform/users/?organization=1
    POST /api/platform/users/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    if request.method == 'GET':
        users = AppUser.objects.all().order_by('-created_at')
        org_id = request.query_params.get('organization')
        if org_id:
            users = users.filter(organization_id=org_id)
        serializer = AppUserPlatformSerializer(users, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = AppUserPlatformSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def platform_user_detail(request, user_id):
    """
    Detalle, actualizar o eliminar usuario
    
    GET/PUT/DELETE /api/platform/users/{id}/
    """
    admin = get_platform_admin_from_request(request)
    if not admin:
        return Response({'error': 'No autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
    
    user = get_object_or_404(AppUser, id=user_id)
    
    if request.method == 'GET':
        serializer = AppUserPlatformSerializer(user)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = AppUserPlatformSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


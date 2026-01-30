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
# CLAIM ACCOUNT (Shadow Organization → Active)
# ============================================

@api_view(['GET'])
@permission_classes([AllowAny])
def verify_claim_token(request, token):
    """
    Verificar si un token de claim es válido
    GET /api/auth/claim/verify/<token>/
    
    Retorna los datos básicos de la organización para mostrar en el formulario
    """
    try:
        # Decodificar token JWT
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get('user_id')
        
        user = User.objects.select_related('organization').get(
            id=user_id,
            invite_pending=True,
            is_active=True
        )
        
        return Response({
            'valid': True,
            'email': user.email,
            'organization_name': user.organization.name if user.organization else None,
            'organization_id': str(user.organization.id) if user.organization else None,
        })
        
    except jwt.ExpiredSignatureError:
        return Response({'valid': False, 'error': 'El enlace ha expirado'}, status=400)
    except jwt.InvalidTokenError:
        return Response({'valid': False, 'error': 'Enlace inválido'}, status=400)
    except User.DoesNotExist:
        return Response({'valid': False, 'error': 'Cuenta ya reclamada o no existe'}, status=400)


@api_view(['POST'])
@permission_classes([AllowAny])
def claim_account(request, token):
    """
    Reclamar cuenta de importador (Shadow Org → Active)
    POST /api/auth/claim/<token>/
    
    Body: { "password": "...", "name": "..." }
    
    Flujo:
    1. Valida el token JWT
    2. Establece password del usuario
    3. Cambia invite_pending → False
    4. Cambia Organization status UNCLAIMED → ACTIVE
    5. Retorna tokens JWT para auto-login
    """
    password = request.data.get('password')
    name = request.data.get('name', '').strip()
    
    if not password or len(password) < 6:
        return Response(
            {'error': 'Password debe tener al menos 6 caracteres'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Decodificar token JWT
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get('user_id')
        
        user = User.objects.select_related('organization').get(
            id=user_id,
            invite_pending=True,
            is_active=True
        )
        
        # Establecer password y activar cuenta
        user.set_password(password)
        if name:
            user.name = name
        user.invite_pending = False
        user.save()
        
        # Activar la organización si estaba UNCLAIMED
        org = user.organization
        if org and org.status == 'UNCLAIMED':
            org.status = 'ACTIVE'
            org.save()
        
        # Generar tokens JWT para auto-login
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'success': True,
            'message': 'Cuenta activada exitosamente',
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })
        
    except jwt.ExpiredSignatureError:
        return Response({'error': 'El enlace ha expirado'}, status=400)
    except jwt.InvalidTokenError:
        return Response({'error': 'Enlace inválido'}, status=400)
    except User.DoesNotExist:
        return Response({'error': 'Cuenta ya reclamada o no existe'}, status=400)


def generate_claim_token(user, expires_days=7):
    """
    Genera un token JWT para reclamar cuenta
    Útil para enviar en emails de invitación
    """
    payload = {
        'user_id': str(user.id),
        'email': user.email,
        'exp': datetime.utcnow() + timedelta(days=expires_days),
        'type': 'claim'
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


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
        """
        Crear nuevo cliente (Shadow Organization)
        
        Flujo:
        - Si org ya existe: solo crea vínculo BusinessRelation
        - Si no existe: crea Shadow Org + User fantasma + BusinessRelation
        """
        serializer = CreatePartnerOrganizationSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            partner_org = serializer.save()
            
            # Determinar si era existente o nueva
            was_existing = getattr(partner_org, '_was_existing', False)
            
            if was_existing:
                message = f'"{partner_org.name}" ya existía en la plataforma. Se agregó a tu agenda.'
            else:
                message = 'Cliente creado exitosamente'
            
            return Response({
                'id': str(partner_org.id),
                'name': partner_org.name,
                'status': partner_org.status,
                'was_existing': was_existing,
                'message': message
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
    
    @action(detail=True, methods=['get'], url_path='emails')
    def get_emails(self, request, pk=None):
        """
        Obtener emails de contacto que YO (exportador) he usado con este cliente
        GET /api/clients/{org_id}/emails/
        
        PRIVACIDAD: Solo devuelve emails de MIS embarques con este cliente.
        Otros exportadores no ven los contactos que yo agregué.
        
        Fuente: Shipment.buyer_email de embarques donde yo soy el exportador
        y el cliente es el importador.
        """
        org = get_user_organization(request.user)
        if not org:
            return Response({'error': 'Usuario sin organización'}, status=400)
        
        # Verificar que el cliente está en mi agenda
        relation = get_object_or_404(
            BusinessRelation,
            host_org=org,
            partner_org_id=pk
        )
        
        partner_org = relation.partner_org
        
        # Obtener emails únicos de MIS embarques con este cliente
        # Esto garantiza privacidad: solo veo los contactos que YO he usado
        from django.db.models import Q
        
        my_shipments = Shipment.objects.filter(
            participants__organization=org,
            participants__role_type='EXPORTER',
            participants__organization_id__in=Shipment.objects.filter(
                participants__organization=partner_org,
                participants__role_type='IMPORTER'
            ).values('id')
        ).filter(
            buyer_email__isnull=False
        ).exclude(
            buyer_email=''
        ).values_list('buyer_email', flat=True).distinct()
        
        # Buscar datos del usuario para cada email
        emails = []
        for email in my_shipments:
            user = User.objects.filter(email__iexact=email).first()
            emails.append({
                'email': email,
                'name': user.name if user else email.split('@')[0],
                'is_pending': user.invite_pending if user else True
            })
        
        return Response(emails)


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
        
        # Obtener email del buyer (preferir shipment.buyer_email)
        buyer = shipment.participants.filter(role_type='BUYER').first()
        if not buyer:
            return Response(
                {'error': 'No hay comprador asignado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        client_email = shipment.buyer_email or buyer.organization.contact_email
        if not client_email:
            return Response(
                {'error': 'El cliente no tiene email configurado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # =============================================
        # CREAR USUARIO FANTASMA SI NO EXISTE
        # Esto permite el claim cuando abran el magic link
        # =============================================
        buyer_org = buyer.organization
        existing_user = User.objects.filter(email__iexact=client_email).first()
        
        if not existing_user:
            # Crear usuario fantasma para este email
            User.objects.create(
                email=client_email,
                name=buyer_org.name,
                organization=buyer_org,
                role='OPERATOR',  # Los adicionales son operadores, no admin
                invite_pending=True,
                is_active=True
            )
            print(f"👤 Usuario fantasma creado: {client_email}")
        
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
    
    Si la organización compradora es UNCLAIMED, retorna claim_required=True
    para que el frontend fuerce el claim antes de permitir firmar.
    """
    magic_link = get_object_or_404(MagicLink, shipment_id=shipment_id, token=token)
    
    if not magic_link.is_valid():
        return Response(
            {'error': 'Este enlace ha expirado o ya fue utilizado'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    shipment = magic_link.shipment
    serializer = SalesConfirmationSerializer(shipment)
    
    response_data = {
        'shipment': serializer.data,
        'can_sign': shipment.status in ['DRAFT', 'SC_SENT'],
        'expires_at': magic_link.expires_at.isoformat()
    }
    
    # Verificar si el BUYER es UNCLAIMED (primera vez)
    buyer = shipment.participants.filter(role_type='BUYER').first()
    if buyer and buyer.organization and buyer.organization.status == 'UNCLAIMED':
        # Buscar usuario fantasma para generar claim token
        pending_user = User.objects.filter(
            organization=buyer.organization,
            invite_pending=True
        ).first()
        
        if pending_user:
            response_data['claim_required'] = True
            response_data['claim_token'] = generate_claim_token(pending_user, expires_days=30)
            response_data['claim_email'] = pending_user.email
            response_data['claim_org_name'] = buyer.organization.name
            response_data['claim_message'] = f'Para firmar este documento, primero debes activar tu cuenta de {buyer.organization.name}'
        else:
            # Org UNCLAIMED pero sin usuario fantasma (caso legacy)
            response_data['claim_required'] = True
            response_data['claim_error'] = 'No hay usuario asociado. Contacta al exportador.'
    else:
        response_data['claim_required'] = False
    
    return Response(response_data)


@api_view(['POST'])
@permission_classes([AllowAny])
def sign_sales_confirmation(request, shipment_id, token):
    """
    Firmar o rechazar Sales Confirmation
    POST /api/sign/{shipment_id}/{token}/submit/
    
    Bloquea la firma si la organización compradora es UNCLAIMED.
    El importador debe hacer claim primero.
    """
    magic_link = get_object_or_404(MagicLink, shipment_id=shipment_id, token=token)
    
    if not magic_link.is_valid():
        return Response(
            {'error': 'Este enlace ha expirado o ya fue utilizado'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    shipment = magic_link.shipment
    
    # Verificar que el BUYER no sea UNCLAIMED
    buyer = shipment.participants.filter(role_type='BUYER').first()
    if buyer and buyer.organization and buyer.organization.status == 'UNCLAIMED':
        return Response(
            {'error': 'Debes activar tu cuenta antes de firmar. Recarga la página para ver las instrucciones.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
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
        
        # Verificar si el comprador puede reclamar cuenta
        claim_token = None
        claim_email = None
        buyer = shipment.participants.filter(role_type='BUYER').first()
        if buyer and buyer.organization:
            # Buscar usuario fantasma asociado a esta organización
            pending_user = User.objects.filter(
                organization=buyer.organization,
                invite_pending=True
            ).first()
            if pending_user:
                claim_token = generate_claim_token(pending_user, expires_days=30)
                claim_email = pending_user.email
        
        response_data = {
            'message': 'Sales Confirmation firmado exitosamente',
            'status': 'SIGNED',
            'signed_by': data['signature_name'],
        }
        
        # Incluir opción de claim si aplica
        if claim_token:
            response_data['claim_available'] = True
            response_data['claim_token'] = claim_token
            response_data['claim_email'] = claim_email
            response_data['claim_message'] = '¿Deseas crear una cuenta para acceder a tus documentos en el futuro?'
        
        return Response(response_data)
    
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
def platform_stats(request):
    """
    Estadísticas completas de la plataforma
    GET /api/platform/stats/
    """
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta
    
    now = timezone.now()
    last_30_days = now - timedelta(days=30)
    last_7_days = now - timedelta(days=7)
    
    # Conteos básicos
    total_orgs = Organization.objects.count()
    exporters = Organization.objects.filter(type='EXPORTER')
    importers = Organization.objects.filter(type='IMPORTER')
    
    total_users = User.objects.filter(is_platform_admin=False).count()
    active_users = User.objects.filter(is_platform_admin=False, is_active=True, invite_pending=False).count()
    pending_users = User.objects.filter(invite_pending=True).count()
    
    total_shipments = Shipment.objects.count()
    recent_shipments = Shipment.objects.filter(created_at__gte=last_30_days).count()
    
    # Embarques por estado
    shipments_by_status = dict(Shipment.objects.values('status').annotate(count=Count('id')).values_list('status', 'count'))
    
    # Organizaciones recientes
    recent_orgs = Organization.objects.filter(
        created_at__gte=last_7_days
    ).order_by('-created_at').values('id', 'name', 'type', 'status', 'created_at')[:5]
    
    # Embarques recientes
    recent_shipment_list = Shipment.objects.select_related().order_by('-created_at')[:5].values(
        'id', 'internal_ref', 'status', 'created_at'
    )
    
    return Response({
        'summary': {
            'total_organizations': total_orgs,
            'exporters': exporters.count(),
            'exporters_active': exporters.filter(status='ACTIVE').count(),
            'importers': importers.count(),
            'importers_unclaimed': importers.filter(status='UNCLAIMED').count(),
            'total_users': total_users,
            'active_users': active_users,
            'pending_users': pending_users,
            'total_shipments': total_shipments,
            'shipments_last_30_days': recent_shipments,
        },
        'shipments_by_status': shipments_by_status,
        'recent_organizations': list(recent_orgs),
        'recent_shipments': list(recent_shipment_list),
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


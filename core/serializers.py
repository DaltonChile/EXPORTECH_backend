"""
Serializers - Arquitectura Multi-Tenant
"""
from rest_framework import serializers
from .models import (
    SystemConfig, Organization, User, BusinessRelation,
    Shipment, ShipmentParticipant, SalesItem, ClientInstructions,
    LabelApproval, PackingVersion, BatchItem, ExportDoc,
    MagicLink, SignatureLog
)


# ============================================
# SYSTEM CONFIG
# ============================================

class SystemConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = ['key', 'value', 'description', 'updated_at']
        read_only_fields = ['updated_at']


# ============================================
# ORGANIZATION
# ============================================

class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer completo de Organization"""
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'tax_id', 'country', 'type', 
            'status', 'default_address', 'contact_email', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class OrganizationMinimalSerializer(serializers.ModelSerializer):
    """Serializer mínimo para dropdowns y referencias"""
    class Meta:
        model = Organization
        fields = ['id', 'name', 'country', 'type', 'status']


class CreatePartnerOrganizationSerializer(serializers.Serializer):
    """
    Crear una organización partner (cliente/proveedor)
    Crea la Organization con status UNCLAIMED y el BusinessRelation
    """
    name = serializers.CharField(max_length=255)
    country = serializers.CharField(max_length=100)
    tax_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    default_address = serializers.CharField(required=False, allow_blank=True)
    alias = serializers.CharField(max_length=100, required=False, allow_blank=True)
    
    def create(self, validated_data):
        host_org = self.context['request'].user.organization
        alias = validated_data.pop('alias', '')
        
        # Crear organización con status UNCLAIMED
        partner_org = Organization.objects.create(
            name=validated_data['name'],
            country=validated_data['country'],
            tax_id=validated_data.get('tax_id', ''),
            contact_email=validated_data.get('contact_email', ''),
            default_address=validated_data.get('default_address', ''),
            type='IMPORTER',
            status='UNCLAIMED'
        )
        
        # Crear relación comercial
        BusinessRelation.objects.create(
            host_org=host_org,
            partner_org=partner_org,
            alias=alias or partner_org.name
        )
        
        return partner_org


# ============================================
# USER
# ============================================

class UserSerializer(serializers.ModelSerializer):
    """Serializer de User"""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'organization', 'organization_name',
            'role', 'is_platform_admin', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'is_platform_admin']


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear usuarios"""
    password = serializers.CharField(write_only=True, min_length=6)
    
    class Meta:
        model = User
        fields = ['email', 'name', 'password', 'organization', 'role']
    
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


# ============================================
# BUSINESS RELATION (Agenda de Clientes)
# ============================================

class BusinessRelationSerializer(serializers.ModelSerializer):
    """Serializer para relaciones comerciales (agenda)"""
    partner_org_details = OrganizationMinimalSerializer(source='partner_org', read_only=True)
    
    class Meta:
        model = BusinessRelation
        fields = ['id', 'partner_org', 'partner_org_details', 'alias', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at']


class ClientListSerializer(serializers.ModelSerializer):
    """
    Serializer para listar clientes (partners) en dropdowns
    Combina datos de Organization + BusinessRelation
    """
    organization_id = serializers.UUIDField(source='partner_org.id')
    name = serializers.CharField(source='partner_org.name')
    country = serializers.CharField(source='partner_org.country')
    contact_email = serializers.EmailField(source='partner_org.contact_email')
    status = serializers.CharField(source='partner_org.status')
    alias = serializers.CharField()
    
    class Meta:
        model = BusinessRelation
        fields = ['organization_id', 'name', 'country', 'contact_email', 'status', 'alias']


# ============================================
# SHIPMENT
# ============================================

class ShipmentParticipantSerializer(serializers.ModelSerializer):
    """Serializer para participantes del embarque"""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    organization_country = serializers.CharField(source='organization.country', read_only=True)
    
    class Meta:
        model = ShipmentParticipant
        fields = ['id', 'organization', 'organization_name', 'organization_country', 'role_type']


class SalesItemSerializer(serializers.ModelSerializer):
    """Serializer para ítems de venta"""
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = SalesItem
        fields = ['id', 'sku', 'description', 'price', 'quantity', 'total']
        read_only_fields = ['id']


class ShipmentListSerializer(serializers.ModelSerializer):
    """Serializer para listado de embarques"""
    buyer_name = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    last_rejection = serializers.SerializerMethodField()
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm',
            'buyer_name', 'etd', 'eta', 'created_at', 'updated_at',
            'total_items', 'total_value', 'last_rejection'
        ]
    
    def get_buyer_name(self, obj):
        buyer = obj.participants.filter(role_type='BUYER').first()
        return buyer.organization.name if buyer else None
    
    def get_total_items(self, obj):
        return obj.sales_items.count()
    
    def get_total_value(self, obj):
        return sum(item.total for item in obj.sales_items.all())
    
    def get_last_rejection(self, obj):
        if obj.status != 'DRAFT':
            return None
        rejection = obj.signatures.filter(status='REJECTED').order_by('-signed_at').first()
        if rejection:
            return {
                'comment': rejection.rejection_comment,
                'rejected_at': rejection.signed_at.isoformat(),
            }
        return None


class ShipmentDetailSerializer(serializers.ModelSerializer):
    """Serializer detallado de embarque"""
    participants = ShipmentParticipantSerializer(many=True, read_only=True)
    sales_items = SalesItemSerializer(many=True, read_only=True)
    buyer = serializers.SerializerMethodField()
    buyer_name = serializers.SerializerMethodField()
    buyer_country = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    last_rejection = serializers.SerializerMethodField()
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm',
            'destination_port', 'payment_terms', 'currency',
            'booking_ref', 'vessel_name', 'etd', 'eta',
            'participants', 'buyer', 'buyer_name', 'buyer_country',
            'sales_items', 'total_value',
            'last_rejection', 'created_by_email',
            'created_at', 'updated_at'
        ]
    
    def get_buyer(self, obj):
        buyer = obj.participants.filter(role_type='BUYER').first()
        if buyer:
            return {
                'id': str(buyer.organization.id),
                'name': buyer.organization.name,
                'country': buyer.organization.country,
                'contact_email': buyer.organization.contact_email,
            }
        return None
    
    def get_buyer_name(self, obj):
        buyer = obj.participants.filter(role_type='BUYER').first()
        return buyer.organization.name if buyer else None
    
    def get_buyer_country(self, obj):
        buyer = obj.participants.filter(role_type='BUYER').first()
        return buyer.organization.country if buyer else None
    
    def get_total_value(self, obj):
        return sum(item.total for item in obj.sales_items.all())
    
    def get_last_rejection(self, obj):
        if obj.status != 'DRAFT':
            return None
        rejection = obj.signatures.filter(status='REJECTED').order_by('-signed_at').first()
        if rejection:
            return {
                'comment': rejection.rejection_comment,
                'rejected_at': rejection.signed_at.isoformat(),
            }
        return None


class ShipmentCreateSerializer(serializers.Serializer):
    """
    Serializer para crear embarque
    Crea el Shipment + ShipmentParticipant (BUYER) + SalesItems
    """
    buyer_org_id = serializers.UUIDField()
    incoterm = serializers.CharField(max_length=10)
    destination_port = serializers.CharField(max_length=255, required=False, allow_blank=True)
    payment_terms = serializers.CharField(max_length=255, required=False, allow_blank=True)
    currency = serializers.CharField(max_length=3, default='USD')
    sales_items = SalesItemSerializer(many=True)
    
    def validate_incoterm(self, value):
        valid = ['EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP']
        if value.upper() not in valid:
            raise serializers.ValidationError(f"Incoterm '{value}' no válido")
        return value.upper()
    
    def validate_buyer_org_id(self, value):
        # Verificar que el buyer está en la agenda del usuario
        user = self.context['request'].user
        if not user.organization:
            raise serializers.ValidationError("Usuario sin organización")
        
        relation_exists = BusinessRelation.objects.filter(
            host_org=user.organization,
            partner_org_id=value
        ).exists()
        
        if not relation_exists:
            raise serializers.ValidationError("Cliente no encontrado en tu agenda")
        
        return value
    
    def create(self, validated_data):
        user = self.context['request'].user
        owner_org = user.organization
        sales_items_data = validated_data.pop('sales_items')
        buyer_org_id = validated_data.pop('buyer_org_id')
        
        # Generar referencia interna
        last_shipment = Shipment.objects.filter(owner_org=owner_org).order_by('-id').first()
        next_number = (last_shipment.id + 1) if last_shipment else 1
        internal_ref = f"EXP-{next_number:04d}"
        
        # Crear embarque
        shipment = Shipment.objects.create(
            owner_org=owner_org,
            internal_ref=internal_ref,
            created_by=user,
            **validated_data
        )
        
        # Agregar participantes
        # Seller = owner_org
        ShipmentParticipant.objects.create(
            shipment=shipment,
            organization=owner_org,
            role_type='SELLER'
        )
        
        # Buyer = cliente seleccionado
        ShipmentParticipant.objects.create(
            shipment=shipment,
            organization_id=buyer_org_id,
            role_type='BUYER'
        )
        
        # Crear items
        for item_data in sales_items_data:
            SalesItem.objects.create(shipment=shipment, **item_data)
        
        return shipment


# ============================================
# SALES CONFIRMATION
# ============================================

class SalesConfirmationSerializer(serializers.ModelSerializer):
    """Datos para generar el PDF de Sales Confirmation"""
    seller = serializers.SerializerMethodField()
    buyer = serializers.SerializerMethodField()
    sales_items = SalesItemSerializer(many=True, read_only=True)
    total_quantity = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm',
            'destination_port', 'payment_terms', 'currency',
            'seller', 'buyer', 'sales_items',
            'total_quantity', 'total_value', 'created_at'
        ]
    
    def get_seller(self, obj):
        seller = obj.participants.filter(role_type='SELLER').first()
        if seller:
            org = seller.organization
            return {
                'name': org.name,
                'tax_id': org.tax_id,
                'country': org.country,
                'address': org.default_address,
            }
        return None
    
    def get_buyer(self, obj):
        buyer = obj.participants.filter(role_type='BUYER').first()
        if buyer:
            org = buyer.organization
            return {
                'name': org.name,
                'tax_id': org.tax_id,
                'country': org.country,
                'address': org.default_address,
                'email': org.contact_email,
            }
        return None
    
    def get_total_quantity(self, obj):
        return sum(item.quantity for item in obj.sales_items.all())
    
    def get_total_value(self, obj):
        return float(sum(item.total for item in obj.sales_items.all()))


class SignSalesConfirmationSerializer(serializers.Serializer):
    """Serializer para firmar/rechazar Sales Confirmation"""
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    signature_name = serializers.CharField(required=False, allow_blank=True)
    rejection_comment = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        if data['action'] == 'approve' and not data.get('signature_name'):
            raise serializers.ValidationError({
                'signature_name': 'Se requiere nombre para firmar'
            })
        if data['action'] == 'reject' and not data.get('rejection_comment'):
            raise serializers.ValidationError({
                'rejection_comment': 'Se requiere comentario para rechazar'
            })
        return data


# ============================================
# PLATFORM ADMIN SERIALIZERS
# ============================================

class PlatformLoginSerializer(serializers.Serializer):
    """Login para Platform Admin"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class OrganizationPlatformSerializer(serializers.ModelSerializer):
    """Organization para vista de Platform Admin"""
    users_count = serializers.SerializerMethodField()
    shipments_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'tax_id', 'country', 'type', 'status',
            'contact_email', 'created_at', 'users_count', 'shipments_count'
        ]
    
    def get_users_count(self, obj):
        return obj.users.count()
    
    def get_shipments_count(self, obj):
        return obj.owned_shipments.count()


class UserPlatformSerializer(serializers.ModelSerializer):
    """User para vista de Platform Admin"""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=6)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'password', 'organization', 'organization_name',
            'role', 'is_platform_admin', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def create(self, validated_data):
        password = validated_data.pop('password', 'exportech123')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user
    
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


# ============================================
# MAESTRO DE MATERIALES
# ============================================

MATERIAL_MASTER = [
    {'sku': 'SKU-101', 'description': 'Salmón Atlántico Entero HG', 'category': 'Salmón', 'default_price': 8.50},
    {'sku': 'SKU-102', 'description': 'Salmón Filete Trim D', 'category': 'Salmón', 'default_price': 12.00},
    {'sku': 'SKU-103', 'description': 'Salmón Filete Trim C', 'category': 'Salmón', 'default_price': 10.50},
    {'sku': 'SKU-104', 'description': 'Salmón Filete Trim E', 'category': 'Salmón', 'default_price': 14.00},
    {'sku': 'SKU-105', 'description': 'Salmón Porción 150g', 'category': 'Salmón', 'default_price': 6.50},
    {'sku': 'SKU-201', 'description': 'Trucha Arcoíris Entero HG', 'category': 'Trucha', 'default_price': 7.00},
    {'sku': 'SKU-202', 'description': 'Trucha Filete Trim D', 'category': 'Trucha', 'default_price': 9.50},
    {'sku': 'SKU-301', 'description': 'Choritos Enteros Cocidos', 'category': 'Moluscos', 'default_price': 4.00},
    {'sku': 'SKU-302', 'description': 'Choritos Media Concha', 'category': 'Moluscos', 'default_price': 5.50},
]


class MaterialMasterSerializer(serializers.Serializer):
    sku = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    default_price = serializers.DecimalField(max_digits=10, decimal_places=2)

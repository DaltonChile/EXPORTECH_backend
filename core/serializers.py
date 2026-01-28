"""
Serializers para la API REST de Exportech
"""
from rest_framework import serializers
from .models import (
    Organization, AppUser, ClientPartner, Shipment, 
    SalesItem, LabelApproval, ClientInstructions,
    PackingVersion, BatchItem, ExportDoc,
    MagicLink, SignatureLog
)


# ============================================
# SERIALIZERS BÁSICOS
# ============================================

class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer para Organization"""
    class Meta:
        model = Organization
        fields = ['id', 'name', 'tax_id', 'plan_type', 'created_at']
        read_only_fields = ['id', 'created_at']


class AppUserSerializer(serializers.ModelSerializer):
    """Serializer para usuarios"""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    
    class Meta:
        model = AppUser
        fields = ['id', 'email', 'role', 'organization', 'organization_name', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class ClientPartnerSerializer(serializers.ModelSerializer):
    """Serializer para clientes/importadores"""
    class Meta:
        model = ClientPartner
        fields = ['id', 'commercial_name', 'country', 'tax_id_foreign', 'default_address', 'contact_email', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def create(self, validated_data):
        # Asignar automáticamente la organización del usuario actual
        request = self.context.get('request')
        if request and request.user.organization:
            validated_data['organization'] = request.user.organization
        return super().create(validated_data)


# ============================================
# MAESTRO DE MATERIALES
# ============================================

class MaterialMasterSerializer(serializers.Serializer):
    """
    Maestro de Materiales - Productos predefinidos
    Evita errores de tipeo en descripciones
    """
    sku = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    default_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)


# Catálogo de productos predefinidos (en producción vendría de BD)
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


# ============================================
# SALES ITEMS (PRODUCTOS EN EL EMBARQUE)
# ============================================

class SalesItemSerializer(serializers.ModelSerializer):
    """Serializer para ítems de venta"""
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = SalesItem
        fields = ['id', 'sku', 'description', 'price', 'quantity', 'total']
        read_only_fields = ['id']


class SalesItemCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear ítems desde el Maestro de Materiales"""
    
    class Meta:
        model = SalesItem
        fields = ['sku', 'description', 'price', 'quantity']
    
    def validate_sku(self, value):
        """Validar que el SKU existe en el Maestro de Materiales"""
        valid_skus = [m['sku'] for m in MATERIAL_MASTER]
        if value not in valid_skus:
            raise serializers.ValidationError(f"SKU '{value}' no existe en el Maestro de Materiales")
        return value


# ============================================
# SHIPMENT (EMBARQUE)
# ============================================

class ShipmentListSerializer(serializers.ModelSerializer):
    """Serializer para listado de embarques"""
    client_name = serializers.CharField(source='client.commercial_name', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    total_items = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm',
            'client', 'client_name', 'created_by_email',
            'etd', 'eta', 'created_at', 'updated_at',
            'total_items', 'total_value'
        ]
    
    def get_total_items(self, obj):
        return obj.sales_items.count()
    
    def get_total_value(self, obj):
        return sum(item.total for item in obj.sales_items.all())


class ShipmentDetailSerializer(serializers.ModelSerializer):
    """Serializer detallado para un embarque"""
    client_name = serializers.CharField(source='client.commercial_name', read_only=True)
    client_country = serializers.CharField(source='client.country', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    sales_items = SalesItemSerializer(many=True, read_only=True)
    total_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm',
            'booking_ref', 'vessel_name', 'etd', 'eta',
            'client', 'client_name', 'client_country',
            'created_by', 'created_by_email',
            'sales_items', 'total_value',
            'created_at', 'updated_at'
        ]
    
    def get_total_value(self, obj):
        return sum(item.total for item in obj.sales_items.all())


class ShipmentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un nuevo embarque (FASE 1)
    
    Incluye la creación de los ítems de venta en una sola operación
    """
    sales_items = SalesItemCreateSerializer(many=True, write_only=True)
    id = serializers.IntegerField(read_only=True)
    internal_ref = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    
    class Meta:
        model = Shipment
        fields = ['id', 'internal_ref', 'status', 'client', 'incoterm', 'destination_port', 'payment_terms', 'currency', 'sales_items']
    
    def validate_incoterm(self, value):
        """Validar incoterms válidos"""
        valid_incoterms = ['EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP']
        if value.upper() not in valid_incoterms:
            raise serializers.ValidationError(f"Incoterm '{value}' no válido")
        return value.upper()
    
    def create(self, validated_data):
        sales_items_data = validated_data.pop('sales_items')
        request = self.context.get('request')
        
        # Generar referencia interna automática
        organization = request.user.organization
        last_shipment = Shipment.objects.filter(organization=organization).order_by('-id').first()
        next_number = (last_shipment.id + 1) if last_shipment else 1
        internal_ref = f"EXP-{next_number:04d}"
        
        # Crear el embarque
        shipment = Shipment.objects.create(
            internal_ref=internal_ref,
            organization=organization,
            created_by=request.user,
            **validated_data
        )
        
        # Crear los ítems de venta
        for item_data in sales_items_data:
            SalesItem.objects.create(shipment=shipment, **item_data)
        
        return shipment


# ============================================
# SALES CONFIRMATION (FASE 1)
# ============================================

class SalesConfirmationSerializer(serializers.ModelSerializer):
    """
    Serializer para generar el documento Sales Confirmation
    Contiene todos los datos necesarios para el PDF
    """
    # Datos de la organización (exportador)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    organization_tax_id = serializers.CharField(source='organization.tax_id', read_only=True)
    
    # Datos del cliente (importador)
    client_name = serializers.CharField(source='client.commercial_name', read_only=True)
    client_country = serializers.CharField(source='client.country', read_only=True)
    client_tax_id = serializers.CharField(source='client.tax_id_foreign', read_only=True)
    client_address = serializers.CharField(source='client.default_address', read_only=True)
    
    # Ítems y totales
    sales_items = SalesItemSerializer(many=True, read_only=True)
    total_quantity = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Shipment
        fields = [
            'id', 'internal_ref', 'status', 'incoterm', 'destination_port', 
            'payment_terms', 'currency',
            'organization_name', 'organization_tax_id',
            'client_name', 'client_country', 'client_tax_id', 'client_address',
            'sales_items', 'total_quantity', 'total_value',
            'created_at'
        ]
    
    def get_total_quantity(self, obj):
        return sum(item.quantity for item in obj.sales_items.all())
    
    def get_total_value(self, obj):
        return float(sum(item.total for item in obj.sales_items.all()))


# ============================================
# FIRMA DE SALES CONFIRMATION (Magic Link)
# ============================================

class SignSalesConfirmationSerializer(serializers.Serializer):
    """
    Serializer para firmar/rechazar Sales Confirmation
    """
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

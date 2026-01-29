"""
Exportech - Modelos de Base de Datos
Arquitectura Multi-Tenant con Organizaciones Unificadas
"""
import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


# ============================================
# 0. CONFIGURACIÓN GLOBAL DEL SISTEMA
# ============================================

class SystemConfig(models.Model):
    """
    Configuración global del sistema (key-value store)
    Ejemplo: MAINTENANCE_MODE = "true"
    """
    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.key} = {self.value}"
    
    class Meta:
        verbose_name = "System Config"
        verbose_name_plural = "System Configs"


# ============================================
# 1. ARQUITECTURA DE ORGANIZACIONES
# ============================================

class Organization(models.Model):
    """
    Organización unificada - puede ser Exportador o Importador
    Un importador puede estar "UNCLAIMED" (creado por exportador, sin cuenta aún)
    """
    TYPE_CHOICES = [
        ('EXPORTER', 'Exportador'),
        ('IMPORTER', 'Importador'),
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Activo'),
        ('UNCLAIMED', 'Sin reclamar'),  # Importador creado por exportador
        ('SUSPENDED', 'Suspendido'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="Ej: Salmones del Sur S.A.")
    tax_id = models.CharField(max_length=50, blank=True, help_text="RUT o Tax ID")
    country = models.CharField(max_length=100, default='Chile')
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='EXPORTER')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    default_address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True, help_text="Email principal de la organización")
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Campo para Shadow Organizations - quién la creó
    created_by_org = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_shadow_orgs',
        help_text="Organización que creó esta shadow org (solo para UNCLAIMED)"
    )
    
    def __str__(self):
        return f"{self.name} ({self.type})"
    
    class Meta:
        ordering = ['name']


class AppUserManager(BaseUserManager):
    """Manager personalizado para User"""
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_platform_admin', True)
        extra_fields.setdefault('role', 'ADMIN')
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Usuario unificado del sistema
    - is_platform_admin: Super admin de la plataforma (dueños de Exportech)
    - invite_pending: Usuario invitado que aún no ha aceptado
    """
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('OPERATOR', 'Operador'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True)
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='users',
        null=True, blank=True  # null para platform admins sin org específica
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='OPERATOR')
    
    # Flags especiales
    is_platform_admin = models.BooleanField(default=False, help_text="Super Admin de Exportech")
    invite_pending = models.BooleanField(default=False, help_text="Invitación pendiente de aceptar")
    
    # Campos Django estándar
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    
    objects = AppUserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    def __str__(self):
        prefix = "[PLATFORM] " if self.is_platform_admin else ""
        return f"{prefix}{self.email}"
    
    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"


class BusinessRelation(models.Model):
    """
    Relación comercial entre organizaciones (agenda de clientes)
    host_org tiene a partner_org en su lista de contactos
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host_org = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='business_relations',
        help_text="Tu organización"
    )
    partner_org = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='partner_of',
        help_text="Tu cliente/proveedor"
    )
    alias = models.CharField(max_length=100, blank=True, help_text="Nombre corto o alias")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.host_org.name} → {self.partner_org.name}"
    
    class Meta:
        unique_together = ['host_org', 'partner_org']
        verbose_name = "Business Relation"
        verbose_name_plural = "Business Relations"


# ============================================
# 2. ESTRUCTURA DEL EMBARQUE
# ============================================

class Shipment(models.Model):
    """Embarque/Exportación"""
    STATUS_CHOICES = [
        ('DRAFT', 'Borrador'),
        ('SC_SENT', 'SC Enviado'),
        ('SIGNED', 'Firmado'),
        ('LABEL_PENDING', 'Etiqueta Pendiente'),
        ('LABEL_APPROVED', 'Etiqueta Aprobada'),
        ('PACKING', 'En Packing'),
        ('SHIPPED', 'Embarcado'),
        ('COMPLETED', 'Completado'),
    ]
    
    id = models.AutoField(primary_key=True)
    owner_org = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='owned_shipments',
        help_text="Organización dueña del embarque"
    )
    internal_ref = models.CharField(max_length=50, help_text="Ej: EXP-001")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Condiciones Comerciales
    incoterm = models.CharField(max_length=10, help_text="Ej: CIF, FOB, CIP")
    destination_port = models.CharField(max_length=255, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    
    # Email de destino para documentos (puede ser diferente al contact_email del buyer)
    buyer_email = models.EmailField(blank=True, help_text="Email donde enviar documentos")
    
    # Logística
    booking_ref = models.CharField(max_length=100, blank=True)
    vessel_name = models.CharField(max_length=255, blank=True)
    etd = models.DateTimeField(null=True, blank=True, help_text="Estimated Time of Departure")
    eta = models.DateTimeField(null=True, blank=True, help_text="Estimated Time of Arrival")
    
    # Auditoría
    created_by = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='created_shipments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.internal_ref}"
    
    class Meta:
        ordering = ['-created_at']


class ShipmentParticipant(models.Model):
    """
    Participantes de un embarque (multi-actor)
    Permite que un embarque tenga múltiples actores con diferentes roles
    """
    ROLE_CHOICES = [
        ('SELLER', 'Vendedor'),
        ('BUYER', 'Comprador'),
        ('CONSIGNEE', 'Consignatario'),
        ('NOTIFY', 'Notify Party'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='shipment_participations'
    )
    role_type = models.CharField(max_length=15, choices=ROLE_CHOICES)
    
    class Meta:
        unique_together = ['shipment', 'organization', 'role_type']
    
    def __str__(self):
        return f"{self.shipment.internal_ref} - {self.organization.name} ({self.role_type})"


# ============================================
# 3. OPERATIVA DEL EMBARQUE
# ============================================

class SalesItem(models.Model):
    """Ítems de venta del embarque"""
    shipment = models.ForeignKey(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='sales_items'
    )
    sku = models.CharField(max_length=50)
    description = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    
    def __str__(self):
        return f"{self.sku} - {self.quantity} units"
    
    @property
    def total(self):
        return self.price * self.quantity


class ClientInstructions(models.Model):
    """Instrucciones del cliente para el embarque"""
    shipment = models.OneToOneField(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='client_instructions'
    )
    consignee_text = models.TextField(blank=True)
    notify_party = models.TextField(blank=True)
    courier_address = models.TextField(blank=True)
    special_marks = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Instructions for {self.shipment.internal_ref}"


class LabelApproval(models.Model):
    """Aprobación de etiquetas"""
    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('APPROVED', 'Aprobado'),
        ('REJECTED', 'Rechazado'),
    ]
    
    shipment = models.OneToOneField(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='label_approval'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    artwork_url = models.URLField(blank=True)
    plant_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Label {self.shipment.internal_ref}: {self.status}"


# ============================================
# 4. PRODUCCIÓN / PACKING
# ============================================

class PackingVersion(models.Model):
    """Versiones del Packing List"""
    shipment = models.ForeignKey(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='packing_versions'
    )
    version_number = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['shipment', 'version_number']
        ordering = ['-version_number']
    
    def __str__(self):
        return f"{self.shipment.internal_ref} v{self.version_number}"


class BatchItem(models.Model):
    """Lotes dentro de una versión del packing"""
    packing_version = models.ForeignKey(
        PackingVersion, 
        on_delete=models.CASCADE, 
        related_name='batch_items'
    )
    batch_code = models.CharField(max_length=100)
    boxes = models.PositiveIntegerField()
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    is_rejected = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.batch_code} - {self.boxes} boxes"


# ============================================
# 5. DOCUMENTOS
# ============================================

class ExportDoc(models.Model):
    """Documentos de exportación"""
    DOC_TYPE_CHOICES = [
        ('INVOICE', 'Factura'),
        ('BL', 'Bill of Lading'),
        ('SANITARY', 'Certificado Sanitario'),
        ('ORIGIN', 'Certificado de Origen'),
        ('PACKING_LIST', 'Packing List'),
        ('OTHER', 'Otro'),
    ]
    
    shipment = models.ForeignKey(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='export_docs'
    )
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES)
    file_url = models.URLField()
    is_final = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.doc_type} - {self.shipment.internal_ref}"


# ============================================
# 6. SALES CONFIRMATION (FIRMA DIGITAL)
# ============================================

class MagicLink(models.Model):
    """Token seguro para acceso sin login"""
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='magic_links'
    )
    token = models.CharField(max_length=100, unique=True)
    email_sent_to = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"Magic Link {self.shipment.internal_ref}"
    
    def is_valid(self):
        from django.utils import timezone
        return self.is_active and not self.used_at and timezone.now() < self.expires_at


class SignatureLog(models.Model):
    """Registro de firma/rechazo de Sales Confirmation"""
    STATUS_CHOICES = [
        ('APPROVED', 'Aprobado'),
        ('REJECTED', 'Rechazado'),
    ]
    
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='signatures'
    )
    magic_link = models.ForeignKey(
        MagicLink,
        on_delete=models.PROTECT,
        related_name='signatures'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    signature_name = models.CharField(max_length=255, blank=True)
    rejection_comment = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    signed_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.shipment.internal_ref} - {self.status}"

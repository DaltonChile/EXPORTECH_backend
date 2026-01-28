from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


# ============================================
# NIVEL 0: EL SAAS (MULTI-TENANT)
# ============================================

class Organization(models.Model):
    """Empresa/Organización que usa el SaaS"""
    PLAN_CHOICES = [
        ('BASIC', 'Basic'),
        ('PRO', 'Pro'),
    ]
    
    name = models.CharField(max_length=255, help_text="Ej: Salmones del Sur S.A.")
    tax_id = models.CharField(max_length=50, unique=True, help_text="RUT: 76.xxx.xxx-k")
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES, default='BASIC')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name


class AppUserManager(BaseUserManager):
    """Manager personalizado para AppUser"""
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
        extra_fields.setdefault('role', 'ADMIN')
        return self.create_user(email, password, **extra_fields)


class AppUser(AbstractBaseUser, PermissionsMixin):
    """Usuario de la aplicación (reemplaza al User de Django)"""
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('OPERADOR', 'Operador'),
        ('PLANTA', 'Planta'),
    ]
    
    email = models.EmailField(unique=True, help_text="Ej: juan@salmones.cl")
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='users',
        null=True, blank=True  # null para superusers sin org
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='OPERADOR')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    objects = AppUserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    def __str__(self):
        return self.email


class ClientPartner(models.Model):
    """Clientes/Partners de la organización"""
    commercial_name = models.CharField(max_length=255, help_text="Ej: Fish USA Inc")
    country = models.CharField(max_length=100)
    tax_id_foreign = models.CharField(max_length=100, blank=True)
    default_address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True, help_text="Email del contacto principal para notificaciones")
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='clients'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.commercial_name} ({self.country})"


# ============================================
# NIVEL 1: LA OPERACIÓN
# ============================================

class Shipment(models.Model):
    """Embarque/Exportación"""
    STATUS_CHOICES = [
        ('DRAFT', 'Borrador'),
        ('SIGNED', 'Firmado'),
        ('SHIPPED', 'Embarcado'),
    ]
    
    internal_ref = models.CharField(max_length=50, help_text="Ej: EXP-001")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    
    # FASE 1: Condiciones Comerciales
    incoterm = models.CharField(max_length=10, help_text="Ej: CIP, FOB, CIF")
    destination_port = models.CharField(max_length=255, blank=True, help_text="Ej: Aarhus, Denmark")
    payment_terms = models.CharField(max_length=255, blank=True, help_text="Ej: 30 days from BL date")
    currency = models.CharField(max_length=3, default='USD', help_text="Ej: USD, EUR")
    
    # Datos Logísticos
    booking_ref = models.CharField(max_length=100, blank=True, help_text="Ej: NAV-9988")
    vessel_name = models.CharField(max_length=255, blank=True, help_text="Ej: LAN Cargo 501")
    etd = models.DateTimeField(null=True, blank=True, help_text="Estimated Time of Departure")
    eta = models.DateTimeField(null=True, blank=True, help_text="Estimated Time of Arrival")
    
    # Relaciones
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='shipments'
    )
    client = models.ForeignKey(
        ClientPartner, 
        on_delete=models.PROTECT, 
        related_name='shipments'
    )
    created_by = models.ForeignKey(
        AppUser, 
        on_delete=models.PROTECT, 
        related_name='shipments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.internal_ref} - {self.client.commercial_name}"


# ============================================
# NIVEL 2: DETALLES DEL EMBARQUE
# ============================================

class SalesItem(models.Model):
    """Ítems de venta del embarque"""
    shipment = models.ForeignKey(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='sales_items'
    )
    sku = models.CharField(max_length=50, help_text="Ej: SKU-TRIM-D")
    description = models.CharField(max_length=255, help_text="Ej: Salmon Filete Trim D")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    
    def __str__(self):
        return f"{self.sku} - {self.quantity} units"
    
    @property
    def total(self):
        return self.price * self.quantity


# ============================================
# NIVEL 3: VALIDACIONES
# ============================================

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
    plant_snapshot = models.JSONField(default=dict, help_text="Códigos congelados")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Label {self.shipment.internal_ref}: {self.status}"


class ClientInstructions(models.Model):
    """Instrucciones del cliente para el embarque"""
    shipment = models.OneToOneField(
        Shipment, 
        on_delete=models.CASCADE, 
        related_name='client_instructions'
    )
    consignee_text = models.TextField(blank=True)
    notify_party = models.TextField(blank=True)
    courier_address = models.TextField(blank=True, help_text="Dirección DHL Final")
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Instructions for {self.shipment.internal_ref}"
    
    class Meta:
        verbose_name_plural = "Client Instructions"


# ============================================
# NIVEL 4: PRODUCCIÓN
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
    batch_code = models.CharField(max_length=100, help_text="Ej: Lote-A")
    boxes = models.PositiveIntegerField()
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    is_rejected = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.batch_code} - {self.boxes} boxes"


# ============================================
# NIVEL 5: DOCUMENTOS
# ============================================

class ExportDoc(models.Model):
    """Documentos de exportación"""
    DOC_TYPE_CHOICES = [
        ('INVOICE', 'Factura'),
        ('BL', 'Bill of Lading'),
        ('SANITARY', 'Certificado Sanitario'),
        ('ORIGIN', 'Certificado de Origen'),
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
# FASE 1: SALES CONFIRMATION
# ============================================

class MagicLink(models.Model):
    """Token seguro para acceso sin login (Magic Link)"""
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
        return f"Magic Link {self.shipment.internal_ref} - {self.email_sent_to}"
    
    def is_valid(self):
        """Verifica si el token es válido"""
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
        return f"{self.shipment.internal_ref} - {self.status} by {self.signature_name or 'Unknown'}"

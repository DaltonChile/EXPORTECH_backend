from django.contrib import admin
from .models import (
    SystemConfig, Organization, User, BusinessRelation,
    Shipment, ShipmentParticipant, SalesItem, ClientInstructions,
    LabelApproval, PackingVersion, BatchItem, ExportDoc,
    MagicLink, SignatureLog
)


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'updated_at']
    search_fields = ['key', 'description']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'country', 'status', 'created_at']
    search_fields = ['name', 'tax_id']
    list_filter = ['type', 'status', 'country']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'organization', 'role', 'is_platform_admin', 'is_active']
    search_fields = ['email', 'name']
    list_filter = ['role', 'is_active', 'is_platform_admin', 'organization']


@admin.register(BusinessRelation)
class BusinessRelationAdmin(admin.ModelAdmin):
    list_display = ['host_org', 'partner_org', 'alias', 'created_at']
    search_fields = ['host_org__name', 'partner_org__name', 'alias']


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ['internal_ref', 'status', 'owner_org', 'incoterm', 'created_at']
    search_fields = ['internal_ref']
    list_filter = ['status', 'incoterm', 'owner_org']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ShipmentParticipant)
class ShipmentParticipantAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'organization', 'role_type']
    list_filter = ['role_type']


@admin.register(SalesItem)
class SalesItemAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'sku', 'description', 'quantity', 'price', 'total']
    search_fields = ['sku', 'description', 'shipment__internal_ref']
    
    def total(self, obj):
        return obj.total
    total.short_description = 'Total'


@admin.register(ClientInstructions)
class ClientInstructionsAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'is_locked', 'created_at']
    list_filter = ['is_locked']


@admin.register(LabelApproval)
class LabelApprovalAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status', 'created_at']
    list_filter = ['status']


@admin.register(PackingVersion)
class PackingVersionAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'version_number', 'is_active', 'created_at']
    list_filter = ['is_active']


@admin.register(BatchItem)
class BatchItemAdmin(admin.ModelAdmin):
    list_display = ['packing_version', 'batch_code', 'boxes', 'weight', 'is_rejected']
    list_filter = ['is_rejected']


@admin.register(ExportDoc)
class ExportDocAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'doc_type', 'is_final', 'uploaded_at']
    list_filter = ['doc_type', 'is_final']


@admin.register(MagicLink)
class MagicLinkAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'email_sent_to', 'is_active', 'created_at', 'expires_at']
    search_fields = ['shipment__internal_ref', 'email_sent_to']
    list_filter = ['is_active']


@admin.register(SignatureLog)
class SignatureLogAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status', 'signature_name', 'ip_address', 'signed_at']
    list_filter = ['status']

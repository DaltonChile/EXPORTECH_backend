from django.contrib import admin
from .models import (
    Organization, AppUser, ClientPartner, Shipment, SalesItem,
    LabelApproval, ClientInstructions, PackingVersion, BatchItem, 
    ExportDoc, MagicLink, SignatureLog, PlatformAdmin
)


@admin.register(PlatformAdmin)
class PlatformAdminAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'is_active', 'last_login', 'created_at']
    search_fields = ['email', 'name']
    list_filter = ['is_active']
    readonly_fields = ['created_at', 'last_login']
    
    def save_model(self, request, obj, form, change):
        if 'password' in form.changed_data:
            obj.set_password(form.cleaned_data['password'])
        super().save_model(request, obj, form, change)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'tax_id', 'plan_type', 'is_active', 'created_at']
    search_fields = ['name', 'tax_id']
    list_filter = ['plan_type', 'is_active']


@admin.register(AppUser)
class AppUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'organization', 'role', 'is_active', 'created_at']
    search_fields = ['email']
    list_filter = ['role', 'is_active', 'organization']


@admin.register(ClientPartner)
class ClientPartnerAdmin(admin.ModelAdmin):
    list_display = ['commercial_name', 'country', 'organization', 'created_at']
    search_fields = ['commercial_name', 'country']
    list_filter = ['country', 'organization']


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ['internal_ref', 'status', 'client', 'incoterm', 'destination_port', 'created_at']
    search_fields = ['internal_ref', 'client__commercial_name']
    list_filter = ['status', 'incoterm', 'organization']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SalesItem)
class SalesItemAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'sku', 'description', 'quantity', 'price', 'total']
    search_fields = ['sku', 'description', 'shipment__internal_ref']
    
    def total(self, obj):
        return obj.total
    total.short_description = 'Total'


@admin.register(MagicLink)
class MagicLinkAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'email_sent_to', 'is_active', 'created_at', 'expires_at', 'used_at']
    search_fields = ['shipment__internal_ref', 'email_sent_to', 'token']
    list_filter = ['is_active']
    readonly_fields = ['created_at', 'used_at']


@admin.register(SignatureLog)
class SignatureLogAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status', 'signature_name', 'ip_address', 'signed_at']
    search_fields = ['shipment__internal_ref', 'signature_name', 'ip_address']
    list_filter = ['status']
    readonly_fields = ['signed_at']


@admin.register(LabelApproval)
class LabelApprovalAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status', 'created_at']
    list_filter = ['status']


@admin.register(ClientInstructions)
class ClientInstructionsAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'is_locked', 'created_at']
    list_filter = ['is_locked']


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

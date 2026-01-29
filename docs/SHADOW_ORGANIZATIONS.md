# Shadow Organizations (Organizaciones Sombra)

Sistema de creación y gestión de importadores sin requerir su registro previo.

---

## Concepto

Permite a un **Exportador** crear clientes (Importadores) en el sistema de forma inmediata, sin esperar a que estos se registren. El importador **debe reclamar su cuenta la primera vez** que recibe un documento.

**Similar a:** Dropbox (compartir con no-usuarios), DocuSign (firmar sin cuenta).

---

## Estados de Organización

| Status | Descripción |
|--------|-------------|
| `ACTIVE` | Organización activa con usuarios reales |
| `UNCLAIMED` | Shadow Org creada por otro, sin cuenta reclamada |
| `SUSPENDED` | Organización suspendida |

---

## Flujo Completo

### PRIMERA VEZ (Org UNCLAIMED)

```
1. Exportador crea cliente con email de contacto (obligatorio)
   → Se crea Organization UNCLAIMED
   → Se crea User fantasma (invite_pending=True, sin password)
   → Se crea BusinessRelation (vínculo)

2. Exportador crea embarque y envía Sales Confirmation
   → Email con Magic Link al importador

3. Importador abre el Magic Link
   → GET /api/sign/{id}/{token}/
   → Backend detecta org UNCLAIMED
   → Retorna claim_required=True + claim_token

4. Frontend muestra: "Para firmar, primero activa tu cuenta"
   → Formulario de claim (password + nombre)

5. Importador hace claim
   → POST /api/auth/claim/{token}/
   → User.invite_pending → False + password
   → Organization.status → ACTIVE

6. Importador ahora puede firmar
   → POST /api/sign/{id}/{token}/submit/
```

### SIGUIENTES VECES (Org ACTIVE)

```
1. Exportador envía documento (puede ser a cualquier email de la org)
2. Importador abre Magic Link → Puede firmar directamente
```

---

## Flujo de Creación de Cliente

```
POST /api/clients/
{
    "name": "Fish USA Inc",
    "country": "United States",
    "tax_id": "XX-YYY",
    "contact_email": "juan@fishusa.com",  // OBLIGATORIO
    "alias": "Fish USA"
}
```

### Lógica del Backend

```
┌─────────────────────────────────────────┐
│  1. Buscar por tax_id o dominio email   │
└─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   YA EXISTE               NO EXISTE
        │                       │
        ▼                       ▼
┌───────────────┐    ┌─────────────────────────┐
│ Solo crear    │    │ Crear:                  │
│ BusinessRel   │    │ • Organization UNCLAIMED│
│ (vínculo)     │    │ • User invite_pending   │
└───────────────┘    │ • BusinessRelation      │
                     └─────────────────────────┘
```

### Respuesta

```json
{
    "id": "uuid-de-la-org",
    "name": "Fish USA Inc",
    "status": "UNCLAIMED",
    "was_existing": false,
    "message": "Cliente creado exitosamente"
}
```

Si ya existía:
```json
{
    "id": "uuid-existente",
    "name": "Fish USA Inc", 
    "status": "ACTIVE",
    "was_existing": true,
    "message": "\"Fish USA Inc\" ya existía en la plataforma. Se agregó a tu agenda."
}
```

---

## Flujo de Claim (Reclamar Cuenta)

El claim es **obligatorio la primera vez** (org UNCLAIMED). El importador no puede firmar sin antes activar su cuenta.

### Respuesta de view_sales_confirmation cuando org es UNCLAIMED

```json
{
    "shipment": { ... },
    "can_sign": true,
    "expires_at": "2026-02-05T...",
    "claim_required": true,
    "claim_token": "eyJ...",
    "claim_email": "juan@fishusa.com",
    "claim_org_name": "Fish USA Inc",
    "claim_message": "Para firmar este documento, primero debes activar tu cuenta de Fish USA Inc"
}
```

### Frontend: Flujo de Primera Vez

```tsx
// Al cargar el Magic Link
const response = await api.get(`/sign/${shipmentId}/${token}/`);

if (response.claim_required) {
    // Mostrar pantalla de activación de cuenta
    showClaimForm({
        email: response.claim_email,
        orgName: response.claim_org_name,
        token: response.claim_token,
        onSuccess: () => {
            // Recargar para poder firmar
            window.location.reload();
        }
    });
} else {
    // Mostrar documento para firmar directamente
    showSignatureForm(response.shipment);
}
```

### Frontend: Mostrar Opción de Claim

```tsx
// Después de firmar exitosamente
if (response.claim_available) {
    showModal({
        title: "¿Crear cuenta?",
        message: response.claim_message,
        email: response.claim_email,
        onAccept: () => navigateTo(`/claim/${response.claim_token}`),
        onDecline: () => showSuccessMessage()
    });
}
```

### 1. Verificar Token (Opcional - Frontend)

```
GET /api/auth/claim/verify/<token>/
```

Respuesta:
```json
{
    "valid": true,
    "email": "juan@fishusa.com",
    "organization_name": "Fish USA Inc",
    "organization_id": "uuid..."
}
```

### 2. Reclamar Cuenta

```
POST /api/auth/claim/<token>/
{
    "password": "mi-password-seguro",
    "name": "Juan Pérez"
}
```

Respuesta (incluye tokens para auto-login):
```json
{
    "success": true,
    "message": "Cuenta activada exitosamente",
    "access": "eyJ...",
    "refresh": "eyJ...",
    "user": {
        "id": "uuid",
        "email": "juan@fishusa.com",
        "name": "Juan Pérez",
        "organization": "uuid",
        "organization_name": "Fish USA Inc",
        "role": "ADMIN"
    }
}
```

---

## Modelo de Datos

### Organization

```python
class Organization(models.Model):
    # ... campos existentes ...
    
    # Nuevo campo para Shadow Orgs
    created_by_org = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_shadow_orgs',
        help_text="Organización que creó esta shadow org"
    )
```

### User

```python
class User(models.Model):
    # ... campos existentes ...
    
    invite_pending = models.BooleanField(
        default=False,
        help_text="Usuario invitado que aún no ha aceptado"
    )
```

---

## Beneficios

| Modelo Tradicional | Shadow Organizations |
|-------------------|----------------------|
| Cada exportador tiene sus propios datos de cliente | Datos centralizados por organización |
| Datos duplicados si 2 exportadores trabajan con mismo cliente | Un solo registro, múltiples vínculos |
| Cliente no puede gestionar su información | Cliente puede reclamar y gestionar su perfil |
| Sin trazabilidad de quién creó qué | `created_by_org` registra origen |

---

## Endpoints Relacionados

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/clients/` | POST | Crear cliente (shadow org) |
| `/api/clients/` | GET | Listar clientes de mi agenda |
| `/api/auth/claim/verify/<token>/` | GET | Verificar token de claim |
| `/api/auth/claim/<token>/` | POST | Reclamar cuenta |

---

## Ejemplo de Email de Invitación

```
Asunto: Salmones del Sur te ha invitado a Exportech

Hola,

Salmones del Sur S.A. te ha agregado como cliente en la plataforma 
Exportech para gestionar embarques de forma digital.

Para acceder a tus documentos y embarques, activa tu cuenta:

[Activar mi cuenta]  ← Link con token

Este enlace expira en 7 días.

---
Exportech - Comercio Internacional Simplificado
```

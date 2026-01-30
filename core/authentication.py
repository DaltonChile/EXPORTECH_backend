"""
Autenticación y Permisos - Arquitectura Multi-Tenant
"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
import jwt
from django.conf import settings


class PlatformAdminAuthentication(BaseAuthentication):
    """
    Autenticación JWT para Platform Admins (is_platform_admin=True)
    Acepta tanto tokens propios como tokens de SimpleJWT
    """
    
    def authenticate(self, request):
        from .models import User
        from rest_framework_simplejwt.tokens import AccessToken
        from rest_framework_simplejwt.exceptions import TokenError
        
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.split(' ')[1]
        
        # Primero intentar con SimpleJWT (sistema unificado)
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            
            user = User.objects.filter(
                id=user_id,
                is_active=True,
                is_platform_admin=True
            ).first()
            
            if user:
                return (user, None)
                
        except TokenError:
            pass
        
        # Fallback: JWT propio (legacy)
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            if payload.get('type') != 'platform_admin':
                return None
            
            user = User.objects.filter(
                id=payload['user_id'],
                is_active=True,
                is_platform_admin=True
            ).first()
            
            if user:
                return (user, None)
            
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            pass
        except Exception:
            pass
        
        return None
    
    def authenticate_header(self, request):
        return 'Bearer realm="api"'


class IsPlatformAdmin(BasePermission):
    """
    Permiso que verifica si el usuario es Platform Admin
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            hasattr(request.user, 'is_platform_admin') and 
            request.user.is_platform_admin
        )


class IsOrganizationMember(BasePermission):
    """
    Permiso base para verificar membresía en organización
    Platform Admins pueden ver todo
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Platform admins pueden ver todo
        if getattr(request.user, 'is_platform_admin', False):
            return True
        
        # Usuario normal debe tener organización
        return request.user.organization is not None


def get_user_organization(user):
    """
    Helper para obtener la organización del usuario
    Retorna None si es platform admin sin org específica
    """
    if not user or not user.is_authenticated:
        return None
    return user.organization


def platform_admin_required(methods=['GET']):
    """
    Decorador para vistas que requieren Platform Admin
    """
    from functools import wraps
    from rest_framework.decorators import api_view, authentication_classes, permission_classes
    
    def decorator(view_func):
        @api_view(methods)
        @authentication_classes([PlatformAdminAuthentication])
        @permission_classes([IsPlatformAdmin])
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator

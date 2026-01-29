"""
Autenticación y permisos personalizados para Platform Admin
"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
import jwt
from django.conf import settings


class PlatformAdminAuthentication(BaseAuthentication):
    """
    Autenticación basada en JWT para Platform Admins
    """
    
    def authenticate(self, request):
        # Import aquí para evitar importación circular
        from .models import PlatformAdmin
        
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.split(' ')[1]
        
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            if payload.get('type') != 'platform_admin':
                return None
            
            admin = PlatformAdmin.objects.filter(
                id=payload['platform_admin_id'],
                is_active=True
            ).first()
            
            if not admin:
                return None
            
            return (admin, None)
            
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None
        except Exception:
            return None
    
    def authenticate_header(self, request):
        return 'Bearer realm="api"'


class IsPlatformAdmin(BasePermission):
    """
    Permiso que verifica si el usuario es un PlatformAdmin
    """
    def has_permission(self, request, view):
        # Import aquí para evitar importación circular
        from .models import PlatformAdmin
        return isinstance(request.user, PlatformAdmin)


def platform_admin_required(methods=['GET']):
    """
    Decorador que combina api_view + autenticación + permisos de Platform Admin
    
    Uso:
        @platform_admin_required(['GET', 'POST'])
        def my_view(request):
            ...
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

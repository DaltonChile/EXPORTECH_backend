"""
Autenticación personalizada para Platform Admin
"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
import jwt
from django.conf import settings
from .models import PlatformAdmin


class PlatformAdminAuthentication(BaseAuthentication):
    """
    Autenticación basada en JWT para Platform Admins
    """
    
    def authenticate(self, request):
        """
        Intenta autenticar la petición usando el token de Platform Admin
        Retorna None si no hay token (permite que otros autenticadores lo intenten)
        """
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.split(' ')[1]
        
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            # Verificar que es un token de Platform Admin
            if payload.get('type') != 'platform_admin':
                return None
            
            # Obtener el admin
            admin = PlatformAdmin.objects.filter(
                id=payload['platform_admin_id'],
                is_active=True
            ).first()
            
            if not admin:
                raise AuthenticationFailed('Platform Admin no encontrado o inactivo')
            
            # Retornar (user, auth) - usamos admin como "user"
            return (admin, None)
            
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token expirado')
        except jwt.InvalidTokenError:
            raise AuthenticationFailed('Token inválido')
        except Exception as e:
            return None
    
    def authenticate_header(self, request):
        """
        Retorna el string a usar en el header WWW-Authenticate
        """
        return 'Bearer realm="api"'


class IsPlatformAdmin(BasePermission):
    """
    Permiso personalizado que verifica si el usuario es un PlatformAdmin
    """
    
    def has_permission(self, request, view):
        return isinstance(request.user, PlatformAdmin)

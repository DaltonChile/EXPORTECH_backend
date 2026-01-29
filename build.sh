#!/usr/bin/env bash
# exit on error
set -o errexit

echo "📦 Instalando dependencias..."
pip install -r requirements.txt

echo "📁 Recolectando archivos estáticos..."
python manage.py collectstatic --no-input

echo "🗄️ Verificando estado de base de datos..."
# Resetear migraciones si las tablas están desincronizadas
python manage.py shell << 'RESET_CHECK'
from django.db import connection
from django.core.management import call_command

try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM core_user LIMIT 1")
    print("✅ Tablas existen, no es necesario resetear")
except Exception as e:
    print(f"⚠️ Tablas no existen o están corruptas: {e}")
    print("🔄 Reseteando migraciones...")
    # Limpiar tabla de migraciones para que Django las aplique de nuevo
    try:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS django_migrations CASCADE")
            cursor.execute("DROP TABLE IF EXISTS django_content_type CASCADE")
            cursor.execute("DROP TABLE IF EXISTS django_admin_log CASCADE")
            cursor.execute("DROP TABLE IF EXISTS django_session CASCADE")
            cursor.execute("DROP TABLE IF EXISTS auth_permission CASCADE")
            cursor.execute("DROP TABLE IF EXISTS auth_group CASCADE")
            cursor.execute("DROP TABLE IF EXISTS auth_group_permissions CASCADE")
            # Eliminar todas las tablas de core
            cursor.execute("DROP TABLE IF EXISTS core_salesitem CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_shipmentsignature CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_shipmentparticipant CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_shipment CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_businessrelation CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_material CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_user CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_organization CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_systemconfig CASCADE")
            # Tablas viejas que pueden existir
            cursor.execute("DROP TABLE IF EXISTS core_clientpartner CASCADE")
            cursor.execute("DROP TABLE IF EXISTS core_platformadmin CASCADE")
        print("✅ Tablas eliminadas, las migraciones se aplicarán desde cero")
    except Exception as drop_error:
        print(f"Error al eliminar tablas: {drop_error}")
RESET_CHECK

echo "🗄️ Ejecutando migraciones de base de datos..."
python manage.py migrate --noinput

echo "👤 Verificando Platform Admin..."
# Crear o actualizar Platform Admin (usando variables de entorno)
python manage.py shell << EOF
import os
from core.models import User

email = os.environ.get('PLATFORM_ADMIN_EMAIL')
password = os.environ.get('PLATFORM_ADMIN_PASSWORD')
name = os.environ.get('PLATFORM_ADMIN_NAME', 'Platform Admin')

if email and password:
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'name': name,
            'is_platform_admin': True,
            'is_staff': True,
            'is_superuser': True,
        }
    )
    # Siempre actualizar la contraseña y nombre
    user.name = name
    user.is_platform_admin = True
    user.set_password(password)
    user.save()
    
    if created:
        print(f"✅ Platform Admin creado: {email}")
    else:
        print(f"🔄 Platform Admin actualizado: {email}")
else:
    print("⚠️ Variables PLATFORM_ADMIN_EMAIL y PLATFORM_ADMIN_PASSWORD no configuradas")
EOF

echo "✅ Build completado exitosamente!"

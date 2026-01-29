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
    print("🔄 Reseteando base de datos completa...")
    try:
        with connection.cursor() as cursor:
            # Eliminar TODO el schema y recrearlo
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
            cursor.execute("GRANT ALL ON SCHEMA public TO postgres")
            cursor.execute("GRANT ALL ON SCHEMA public TO public")
        print("✅ Schema reseteado, las migraciones se aplicarán desde cero")
    except Exception as drop_error:
        print(f"Error al resetear schema: {drop_error}")
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

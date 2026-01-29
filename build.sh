#!/usr/bin/env bash
# exit on error
set -o errexit

echo "📦 Instalando dependencias..."
pip install -r requirements.txt

echo "📁 Recolectando archivos estáticos..."
python manage.py collectstatic --no-input

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

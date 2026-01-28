#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Crear Platform Admin si no existe (usando variables de entorno)
python manage.py shell << EOF
import os
from core.models import PlatformAdmin

email = os.environ.get('PLATFORM_ADMIN_EMAIL')
password = os.environ.get('PLATFORM_ADMIN_PASSWORD')
name = os.environ.get('PLATFORM_ADMIN_NAME', 'Platform Admin')

if email and password:
    if not PlatformAdmin.objects.filter(email=email).exists():
        admin = PlatformAdmin(email=email, name=name)
        admin.set_password(password)
        admin.save()
        print(f"✅ Platform Admin creado: {email}")
    else:
        print(f"ℹ️ Platform Admin ya existe: {email}")
else:
    print("⚠️ Variables PLATFORM_ADMIN_EMAIL y PLATFORM_ADMIN_PASSWORD no configuradas")
EOF

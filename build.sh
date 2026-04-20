#!/usr/bin/env bash
# exit on error
set -o errexit

python -m pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Create superuser if it doesn't exist
python manage.py shell -c " from django.contrib.auth import get_user_model User = get_user_model() User.objects.filter(email='superadmin@gmail.com').delete() u = User.objects.create_superuser('superadmin', 'superadmin@gmail.com', 'StudyAdmin@2025!') print('Superuser created:', u.email)"


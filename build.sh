#!/usr/bin/env bash
# exit on error
set -o errexit

python -m pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
email = 'superadmin@gmail.com'
password = 'StudyAdmin@2025!'

# Delete any existing user with this email to prevent 'already exists' errors
User.objects.filter(email=email).delete()

# Create the superuser with email as the username
User.objects.create_superuser(email, email, password)
print('SUPERUSER CREATED SUCCESSFULLY')
"
"
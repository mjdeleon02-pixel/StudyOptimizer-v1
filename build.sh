#!/usr/bin/env bash
# exit on error
set -o errexit

python -m pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Create superuser if it doesn't exist
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
email = 'superadmin@gmail.com'
password = 'StudyAdmin@2025!'

# Clean up existing to avoid conflicts
User.objects.filter(email=email).delete()

# Create the user. 
# Note: We use the email as the FIRST argument (username) 
u = User.objects.create_superuser(email, email, password)
print(f'Superuser created successfully: {u.email}')
"
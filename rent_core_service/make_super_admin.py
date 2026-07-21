import os
import django
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python make_super_admin.py <email>")
        return
        
    email_to_search = sys.argv[1]
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rent_core_service.settings')
    django.setup()

    from Users.models import User
    
    users = User.objects.filter(email__iexact=email_to_search)
    if users.exists():
        for u in users:
            u.role = 'admin'
            u.admin_level = 'super_admin'
            u.save()
            print(f"Successfully updated {u.email} to super_admin!")
    else:
        print(f"User with email '{email_to_search}' not found.")

if __name__ == "__main__":
    main()

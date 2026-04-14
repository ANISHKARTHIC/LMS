from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update default admin user from environment settings."

    def handle(self, *args, **options):
        username = settings.DEFAULT_ADMIN_USERNAME
        email = settings.DEFAULT_ADMIN_EMAIL
        password = settings.DEFAULT_ADMIN_PASSWORD

        if not username or not password:
            self.stdout.write(self.style.ERROR("DEFAULT_ADMIN_USERNAME and DEFAULT_ADMIN_PASSWORD are required."))
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        if user.email != email:
            user.email = email

        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created default admin user '{username}'."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated default admin user '{username}'."))

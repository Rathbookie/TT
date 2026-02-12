from django.core.management.base import BaseCommand
from users.models import Role


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for name in [
            Role.ADMIN,
            Role.TASK_CREATOR,
            Role.TASK_RECEIVER,
        ]:
            Role.objects.get_or_create(name=name)

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from context.models import Tenant


class User(AbstractUser):
    first_name = models.CharField(max_length=150, default ="Temp")
    last_name = models.CharField(max_length=150, default ="User")

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
    )


# ---------- ROLES ----------

class Role(models.Model):
    ADMIN = "ADMIN"
    TASK_CREATOR = "TASK_CREATOR"
    TASK_RECEIVER = "TASK_RECEIVER"

    ROLE_CHOICES = [
        (ADMIN, "Admin"),
        (TASK_CREATOR, "Task Creator"),
        (TASK_RECEIVER, "Task Receiver"),
    ]

    name = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        unique=True,
    )

    def __str__(self):
        return self.name


class UserRole(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tenant_user_roles",
    )

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_users",
    )

    class Meta:
        unique_together = ("user", "tenant", "role")

    def __str__(self):
        return f"{self.user} → {self.role.name} ({self.tenant})"

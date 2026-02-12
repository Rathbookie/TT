import uuid
from django.db import models


class Tenant(models.Model):

    STATUS_CHOICES = (
        ("active", "Active"),
        ("suspended", "Suspended"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TenantAwareModel(models.Model):
    """
    Any model that belongs to a tenant must inherit this.
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        editable=False,
        related_name="%(class)s_objects",
    )

    class Meta:
        abstract = True

from context.models import Tenant
from django.db import models
from django.conf import settings

User = settings.AUTH_USER_MODEL


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)

    def active(self):
        return self.filter(is_deleted=False)


class TenantManager(models.Manager):
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_tenant(self, tenant):
        return self.get_queryset().for_tenant(tenant)

    def active(self):
        return self.get_queryset().active()


class Task(models.Model):

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not Started"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        BLOCKED = "BLOCKED", "Blocked"
        WAITING_REVIEW = "WAITING_REVIEW", "Waiting Review"
        DONE = "DONE", "Done"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        P1 = "P1", "Critical"
        P2 = "P2", "High"
        P3 = "P3", "Normal"
        P4 = "P4", "Low"

    objects = TenantManager()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tasks_created",
    )

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tasks_assigned",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )

    priority = models.CharField(
        max_length=2,
        choices=Priority.choices,
        default=Priority.P3,
    )

    blocked_reason = models.TextField(
        blank=True,
        null=True,
    )

    # ✅ CHANGED FROM DateField → DateTimeField
    due_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    # -------------------
    # OPTIMISTIC LOCKING
    # -------------------
    version = models.PositiveIntegerField(default=1)

    # -------------------
    # AUDIT FIELDS
    # -------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks_updated",
    )

    # -------------------
    # SOFT DELETE FIELDS
    # -------------------
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks_deleted",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["tenant", "is_deleted"]),
            models.Index(fields=["tenant", "due_date"]),  # optional future optimization
        ]

    def __str__(self):
        return self.title


class TaskHistory(models.Model):

    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        SOFT_DELETED = "SOFT_DELETED", "Soft Deleted"
        SUBMITTED = "SUBMITTED", "Submitted for Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="task_history",
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="history",
    )

    action = models.CharField(
        max_length=32,
        choices=Action.choices,
    )

    performed_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="task_history_actions",
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    # Snapshot fields
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=32)
    priority = models.CharField(max_length=2, null=True, blank=True)

    # ✅ CHANGED FROM DateField → DateTimeField
    due_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["tenant", "task"]),
            models.Index(fields=["timestamp"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("TaskHistory records are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("TaskHistory records cannot be deleted.")

    def __str__(self):
        return f"{self.task.id} - {self.action} - {self.timestamp}"


class TaskAttachment(models.Model):

    class Type(models.TextChoices):
        REQUIREMENT = "REQUIREMENT", "Requirement"
        SUBMISSION = "SUBMISSION", "Submission"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="task_attachments",
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_attachments",
    )

    file = models.FileField(upload_to="task_attachments/")
    original_name = models.CharField(max_length=255)

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.REQUIREMENT,
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["tenant", "task"]),
        ]
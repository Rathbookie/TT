"""
core_api/models.py

Hierarchy:
    Tenant (context.models — already has id/UUID, name, slug, status)
        └── Division          e.g. Marketing, Sales, Engineering, HR
              └── Section     optional — e.g. Mobile App, Backend, Brand
                    └── Board e.g. Sprint 3, Q1 Campaign, Hiring Pipeline
                          └── Task
                                └── Subtask (self-referential via parent FK)

URL structure (Tenant.slug already exists — no duplication needed):
    /{tenant.slug}/{division.slug}/
    /{tenant.slug}/{division.slug}/{board.slug}/
    /{tenant.slug}/{division.slug}/{section.slug}/{board.slug}/
    /{tenant.slug}/task/TAS-123

Design decisions:
    - OrganizationProfile is a minimal one-to-one extension of Tenant.
      Tenant already has name + slug — this only adds task_sequence + plan.
    - Division/Section/Board each have slugs unique within their parent.
    - Board belongs to EITHER Division OR Section — enforced in clean().
    - BoardStatus replaces hardcoded Task.Status — fully custom per board.
    - Task.ref_id (TAS-123) assigned atomically via select_for_update.
    - Task.assignees is M2M via TaskAssignee through model.
    - Task.parent is self-referential FK for subtasks (no separate model).
    - All existing audit/soft-delete/optimistic locking patterns preserved.
"""

from django.db import models, transaction
from django.conf import settings
from django.utils.text import slugify
from context.models import Tenant
from workflows.models import Workflow, WorkflowStage

User = settings.AUTH_USER_MODEL


# =============================================================================
# SHARED QUERYSET / MANAGER
# =============================================================================

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


# =============================================================================
# ORGANIZATION PROFILE
# Minimal one-to-one extension of Tenant.
# Tenant already has: id (UUID), name, slug, status, created_at
# This only adds: task_sequence (for TAS-123 IDs), plan (billing tier)
# Created automatically via signal when a new Tenant is saved.
# =============================================================================

class OrganizationProfile(models.Model):

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=True,
    )

    # Atomic per-tenant counter. TAS-1, TAS-2, TAS-3...
    task_sequence = models.PositiveIntegerField(default=0)

    plan = models.CharField(
        max_length=20,
        default="free",
        choices=[
            ("free", "Free"),
            ("starter", "Starter"),
            ("growth", "Growth"),
            ("enterprise", "Enterprise"),
        ],
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization Profile"

    def __str__(self):
        return f"{self.tenant.name} ({self.plan})"

    def next_task_ref(self):
        """
        Atomically increments task_sequence and returns the new value.
        Must be called inside a transaction with select_for_update on self.

        Called automatically in Task.save() — do not call manually.
        """
        OrganizationProfile.objects.filter(pk=self.pk).update(
            task_sequence=models.F("task_sequence") + 1
        )
        self.refresh_from_db(fields=["task_sequence"])
        return self.task_sequence


# =============================================================================
# DIVISION
# 2nd level of the hierarchy.
# Examples: Marketing, Sales, Engineering, HR
# URL segment: /{tenant.slug}/{division.slug}/
# =============================================================================

class Division(models.Model):
    class DefaultPermission(models.TextChoices):
        FULL_EDIT = "FULL_EDIT", "Full edit"
        COMMENT_ONLY = "COMMENT_ONLY", "Comment only"
        VIEW_ONLY = "VIEW_ONLY", "View only"

    objects = TenantManager()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="divisions",
    )

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)  # unique within tenant via unique_together
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Emoji or icon name")
    color = models.CharField(max_length=7, blank=True, help_text="Hex e.g. #3B82F6")
    default_permission = models.CharField(
        max_length=20,
        choices=DefaultPermission.choices,
        default=DefaultPermission.FULL_EDIT,
    )
    is_private = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="divisions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("tenant", "slug")]
        indexes = [
            models.Index(fields=["tenant", "is_deleted"]),
            models.Index(fields=["tenant", "slug"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tenant.name} / {self.name}"


# =============================================================================
# DIVISION MEMBER
# Tracks users in a division and their role within it.
# Note: this is separate from the global UserRole on users.models.
# DivisionMember.role controls what a user can do within a specific division.
# =============================================================================

class DivisionMember(models.Model):

    class Role(models.TextChoices):
        ADMIN   = "ADMIN",   "Admin"
        MANAGER = "MANAGER", "Manager"
        MEMBER  = "MEMBER",  "Member"
        VIEWER  = "VIEWER",  "Viewer"

    division = models.ForeignKey(
        Division,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="division_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("division", "user")]
        indexes = [
            models.Index(fields=["division", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.division} ({self.role})"


# =============================================================================
# SECTION (optional layer)
# 3rd level — optional grouping within a Division.
# Examples: Mobile App, Backend, Brand, Outbound Sales
# URL segment: /{tenant.slug}/{division.slug}/{section.slug}/
# A Board can live directly under a Division OR inside a Section.
# =============================================================================

class Section(models.Model):

    objects = TenantManager()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    division = models.ForeignKey(
        Division,
        on_delete=models.CASCADE,
        related_name="sections",
    )

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)  # unique within division via unique_together
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=7, blank=True)
    order = models.PositiveIntegerField(default=0)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sections_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("division", "slug")]
        indexes = [
            models.Index(fields=["tenant", "division"]),
            models.Index(fields=["division", "is_deleted"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.division} / {self.name}"


# =============================================================================
# BOARD
# 4th level — where tasks actually live.
# Examples: Sprint 3, Q1 Campaign, Hiring Pipeline, Product Backlog
#
# CONSTRAINT: A Board belongs to EITHER a Division OR a Section.
# Never both. Never neither. Enforced in clean() and save().
#
# URL (under Division):  /{tenant.slug}/{division.slug}/{board.slug}/
# URL (under Section):   /{tenant.slug}/{division.slug}/{section.slug}/{board.slug}/
# =============================================================================

class Board(models.Model):

    class ViewType(models.TextChoices):
        LIST     = "LIST",     "List"
        KANBAN   = "KANBAN",   "Kanban"
        CALENDAR = "CALENDAR", "Calendar"
        GANTT    = "GANTT",    "Gantt"
        TABLE    = "TABLE",    "Table"

    objects = TenantManager()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="boards",
    )

    # Exactly one must be set — enforced in clean()
    division = models.ForeignKey(
        Division,
        on_delete=models.CASCADE,
        related_name="boards",
        null=True, blank=True,
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="boards",
        null=True, blank=True,
    )

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150)
    description = models.TextField(blank=True)
    default_view = models.CharField(
        max_length=20,
        choices=ViewType.choices,
        default=ViewType.LIST,
    )
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=7, blank=True)
    order = models.PositiveIntegerField(default=0)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="boards_deleted",
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="boards_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["tenant", "is_deleted"]),
            models.Index(fields=["division"]),
            models.Index(fields=["section"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.division_id and self.section_id:
            raise ValidationError(
                "A Board cannot belong to both a Division and a Section."
            )
        if not self.division_id and not self.section_id:
            raise ValidationError(
                "A Board must belong to either a Division or a Section."
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        parent = self.section or self.division
        return f"{parent} / {self.name}"


# =============================================================================
# BOARD STATUS
# Custom statuses per board. Replaces the hardcoded Task.Status TextChoices.
# A default set of 6 statuses is created via signal on Board creation.
# Users can add, rename, reorder statuses. Default ones are protected.
# =============================================================================

class BoardStatus(models.Model):

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="statuses",
    )
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#6B7280")
    order = models.PositiveIntegerField(default=0)
    is_terminal = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)  # protected from deletion

    class Meta:
        ordering = ["order"]
        unique_together = [("board", "name")]
        indexes = [
            models.Index(fields=["board", "order"]),
        ]

    def __str__(self):
        return f"{self.board.name} / {self.name}"


# =============================================================================
# TASK
# Core model. Supports:
#   - Subtasks via self-referential parent FK
#   - Multiple assignees via M2M (TaskAssignee through model)
#   - Custom per-board statuses (FK → BoardStatus)
#   - Per-org human-readable ref IDs (TAS-123)
#   - Full audit trail, soft delete, optimistic locking (from original)
#
# URL: /{tenant.slug}/task/TAS-123
# =============================================================================

class Task(models.Model):

    class Priority(models.TextChoices):
        P1 = "P1", "Critical"
        P2 = "P2", "High"
        P3 = "P3", "Normal"
        P4 = "P4", "Low"

    objects = TenantManager()

    # --- Identity ---
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    ref_id = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Auto-assigned on creation. e.g. TAS-42",
    )

    # --- Hierarchy ---
    division = models.ForeignKey(
        Division,
        on_delete=models.SET_NULL,
        related_name="tasks",
        null=True, blank=True,
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="tasks",
        null=True, blank=True,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="subtasks",
        help_text="Set this to make the task a subtask of another task.",
    )
    order = models.PositiveIntegerField(default=0)

    # --- Content ---
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # --- Status & Priority ---
    status = models.ForeignKey(
        BoardStatus,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tasks",
    )
    priority = models.CharField(
        max_length=2,
        choices=Priority.choices,
        default=Priority.P3,
    )
    blocked_reason = models.TextField(blank=True, null=True)

    # --- Dates ---
    due_date = models.DateTimeField(blank=True, null=True)
    start_date = models.DateTimeField(blank=True, null=True)
    estimated_hours = models.DecimalField(
        max_digits=6, decimal_places=2,
        null=True, blank=True,
    )

    # --- People ---
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tasks_created",
    )
    assignees = models.ManyToManyField(
        User,
        related_name="tasks_assigned",
        blank=True,
        through="TaskAssignee",
        through_fields=("task", "user"),  # disambiguates from assigned_by FK
    )

    # --- Workflow (preserved from original) ---
    workflow = models.ForeignKey(
        Workflow,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    stage = models.ForeignKey(
        WorkflowStage,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )

    # --- Optimistic locking (preserved) ---
    version = models.PositiveIntegerField(default=1)

    # --- Audit (preserved) ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks_updated",
    )

    # --- Soft delete (preserved) ---
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks_deleted",
    )

    class Meta:
        ordering = ["order", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["tenant", "is_deleted"]),
            models.Index(fields=["tenant", "due_date"]),
            models.Index(fields=["tenant", "ref_id"]),
            models.Index(fields=["division"]),
            models.Index(fields=["board", "order"]),
            models.Index(fields=["parent"]),
        ]

    def save(self, *args, **kwargs):
        # Keep task division aligned with the selected board.
        if self.board_id:
            board_division_id = self.board.division_id
            if board_division_id is None and self.board.section_id:
                board_division_id = self.board.section.division_id
            self.division_id = board_division_id

        if not self.ref_id and self.tenant_id:
            with transaction.atomic():
                profile = OrganizationProfile.objects.select_for_update().get(
                    tenant_id=self.tenant_id
                )
                self.ref_id = f"TAS-{profile.next_task_ref()}"
        super().save(*args, **kwargs)

    @property
    def is_subtask(self):
        return self.parent_id is not None

    def __str__(self):
        return f"[{self.ref_id}] {self.title}"


# =============================================================================
# TASK ASSIGNEE
# Through model for Task ↔ User M2M.
# Records who made the assignment and when.
# =============================================================================

class TaskAssignee(models.Model):

    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("task", "user")]
        indexes = [
            models.Index(fields=["task"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user} on [{self.task.ref_id}]"


# =============================================================================
# TASK DEPENDENCY
# Blocking relationships. Used for Gantt chart critical path rendering.
# "task is blocked by blocker" — task cannot proceed until blocker is done.
# =============================================================================

class TaskDependency(models.Model):

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="dependencies",
    )
    blocker = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="blocking",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        unique_together = [("task", "blocker")]
        indexes = [
            models.Index(fields=["task"]),
            models.Index(fields=["blocker"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.task_id == self.blocker_id:
            raise ValidationError("A task cannot depend on itself.")

    def __str__(self):
        return f"[{self.task.ref_id}] blocked by [{self.blocker.ref_id}]"


# =============================================================================
# TASK COMMENT
# Threaded. Top-level comments have parent=None. Replies have parent=<comment>.
# Soft-deletable — content replaced with "[deleted]" on delete, author kept.
# =============================================================================

class TaskComment(models.Model):

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="task_comments",
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="replies",
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_comments",
    )
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["task", "created_at"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        return f"Comment by {self.author} on [{self.task.ref_id}]"


# =============================================================================
# TASK HISTORY
# Immutable append-only audit log. Preserved from original.
# Added: status_name snapshot (instead of FK), changes JSONField for diffs.
# =============================================================================

class TaskHistory(models.Model):

    class Action(models.TextChoices):
        CREATED      = "CREATED",      "Created"
        UPDATED      = "UPDATED",      "Updated"
        SOFT_DELETED = "SOFT_DELETED", "Soft Deleted"
        SUBMITTED    = "SUBMITTED",    "Submitted for Review"
        APPROVED     = "APPROVED",     "Approved"
        REJECTED     = "REJECTED",     "Rejected"
        ASSIGNED     = "ASSIGNED",     "Assigned"
        UNASSIGNED   = "UNASSIGNED",   "Unassigned"
        MOVED        = "MOVED",        "Moved to Board"
        COMMENTED    = "COMMENTED",    "Commented"

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
    action = models.CharField(max_length=32, choices=Action.choices)
    performed_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="task_history_actions",
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    # Snapshot fields — point-in-time state of the task
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status_name = models.CharField(max_length=50, blank=True)  # name, not FK
    priority = models.CharField(max_length=2, null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)

    # Diff — e.g. {"status": {"from": "In Progress", "to": "Done"}}
    changes = models.JSONField(default=dict, blank=True)

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
        return f"[{self.task.ref_id}] {self.action} @ {self.timestamp}"


# =============================================================================
# TASK PROOF
# Generic proof submissions used by workflow transition requirements.
# =============================================================================

class TaskProof(models.Model):
    class Type(models.TextChoices):
        FILE = "FILE", "File"
        TEXT = "TEXT", "Text"
        URL = "URL", "Url"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="task_proofs",
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="proofs",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="submitted_task_proofs",
    )
    type = models.CharField(max_length=10, choices=Type.choices)
    file = models.FileField(upload_to="task_proofs/%Y/%m/", null=True, blank=True)
    text = models.TextField(blank=True)
    url = models.URLField(blank=True)
    label = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["tenant", "task"]),
            models.Index(fields=["task", "type"]),
        ]

    def __str__(self):
        return f"{self.task.ref_id} - {self.type}"


# =============================================================================
# TASK ATTACHMENT
# Preserved from original. Added file_size + mime_type. Path organised by date.
# Note: For production swap FileField → URLField + S3 presigned uploads.
# =============================================================================

class TaskAttachment(models.Model):

    class Type(models.TextChoices):
        REQUIREMENT = "REQUIREMENT", "Requirement"
        SUBMISSION  = "SUBMISSION",  "Submission"
        REFERENCE   = "REFERENCE",   "Reference"

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
    file = models.FileField(upload_to="task_attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
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

    def __str__(self):
        return f"{self.original_name} on [{self.task.ref_id}]"


# Semantic alias for per-board task statuses.
TaskStatus = BoardStatus

from django.db import models
from django.db.models import Q
from django.conf import settings

from context.models import Tenant


class Workflow(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="workflows",
    )
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="uniq_workflow_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(is_default=True),
                name="uniq_default_workflow_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.tenant} - {self.name}"


class WorkflowStage(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="stages",
    )
    name = models.CharField(max_length=64)
    order = models.PositiveIntegerField()
    is_terminal = models.BooleanField(default=False)
    requires_attachments = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    color = models.CharField(max_length=7, default="#6B7280")

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "name"],
                name="uniq_stage_name_per_workflow",
            ),
            models.UniqueConstraint(
                fields=["workflow", "order"],
                name="uniq_stage_order_per_workflow",
            ),
        ]

    def __str__(self):
        return f"{self.workflow.name} - {self.name}"


class WorkflowTransition(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="transitions",
    )
    from_stage = models.ForeignKey(
        WorkflowStage,
        on_delete=models.CASCADE,
        related_name="outgoing_transitions",
    )
    to_stage = models.ForeignKey(
        WorkflowStage,
        on_delete=models.CASCADE,
        related_name="incoming_transitions",
    )
    allowed_role = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "from_stage", "to_stage", "allowed_role"],
                name="uniq_transition_per_role",
            )
        ]

    def __str__(self):
        return (
            f"{self.workflow.name}: {self.from_stage.name} -> "
            f"{self.to_stage.name} ({self.allowed_role})"
        )


class WorkflowStatus(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="statuses",
    )
    name = models.CharField(max_length=64)
    order = models.PositiveIntegerField(default=0)
    is_terminal = models.BooleanField(default=False)
    color = models.CharField(max_length=7, default="#6B7280")

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "name"],
                name="uniq_status_name_per_workflow",
            ),
            models.UniqueConstraint(
                fields=["workflow", "order"],
                name="uniq_status_order_per_workflow",
            ),
        ]

    def __str__(self):
        return f"{self.workflow.name} - {self.name}"


class TransitionRule(models.Model):
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="transition_rules",
    )
    from_status = models.ForeignKey(
        WorkflowStatus,
        on_delete=models.CASCADE,
        related_name="outgoing_rules",
    )
    to_status = models.ForeignKey(
        WorkflowStatus,
        on_delete=models.CASCADE,
        related_name="incoming_rules",
    )
    allowed_roles = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "from_status", "to_status"],
                name="uniq_transition_rule_per_status_pair",
            )
        ]

    def __str__(self):
        return f"{self.workflow.name}: {self.from_status.name} -> {self.to_status.name}"


class ProofRequirement(models.Model):
    class Type(models.TextChoices):
        FILE = "FILE", "File"
        TEXT = "TEXT", "Text"
        URL = "URL", "Url"

    transition_rule = models.ForeignKey(
        TransitionRule,
        on_delete=models.CASCADE,
        related_name="proof_requirements",
    )
    type = models.CharField(max_length=10, choices=Type.choices)
    label = models.CharField(max_length=255)
    is_mandatory = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["transition_rule", "is_mandatory"]),
        ]

    def __str__(self):
        return f"{self.transition_rule} - {self.label}"


class WorkflowPreset(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=120)
    description = models.TextField()
    color = models.CharField(max_length=20, default="blue")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class WorkflowPresetStage(models.Model):
    preset = models.ForeignKey(
        WorkflowPreset,
        on_delete=models.CASCADE,
        related_name="stages",
    )
    name = models.CharField(max_length=64)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preset", "name"],
                name="uniq_preset_stage_name",
            ),
            models.UniqueConstraint(
                fields=["preset", "order"],
                name="uniq_preset_stage_order",
            ),
        ]

    def __str__(self):
        return f"{self.preset.title}: {self.name}"


class WorkflowPresetWidget(models.Model):
    preset = models.ForeignKey(
        WorkflowPreset,
        on_delete=models.CASCADE,
        related_name="widgets",
    )
    name = models.CharField(max_length=120)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preset", "name"],
                name="uniq_preset_widget_name",
            ),
            models.UniqueConstraint(
                fields=["preset", "order"],
                name="uniq_preset_widget_order",
            ),
        ]

    def __str__(self):
        return f"{self.preset.title}: {self.name}"


class ModuleDefinition(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField()
    category = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TenantModule(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tenant_modules",
    )
    module = models.ForeignKey(
        ModuleDefinition,
        on_delete=models.CASCADE,
        related_name="tenant_states",
    )
    is_enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "module"],
                name="uniq_tenant_module",
            )
        ]

    def __str__(self):
        return f"{self.tenant} - {self.module.name} ({self.is_enabled})"


class DashboardConfig(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "PRIVATE", "Private"
        INTERNAL = "INTERNAL", "Shared Internal"
        PUBLIC = "PUBLIC", "Public Link"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="dashboard_configs",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_dashboards",
    )
    name = models.CharField(max_length=120, default="Dashboard")
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.INTERNAL,
    )
    is_default = models.BooleanField(default=True)
    global_filters = models.JSONField(default=dict, blank=True)
    widgets = models.JSONField(default=list, blank=True)
    auto_refresh_seconds = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="uniq_dashboard_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(is_default=True),
                name="uniq_default_dashboard_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.tenant} - {self.name}"

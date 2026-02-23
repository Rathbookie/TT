from django.db import models
from django.db.models import Q

from context.models import Tenant


class Workflow(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="workflows",
    )
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

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


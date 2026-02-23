from rest_framework.exceptions import PermissionDenied

from .models import Workflow, WorkflowStage, WorkflowTransition


def get_default_workflow_for_tenant(tenant):
    return (
        Workflow.objects.filter(tenant=tenant, is_default=True)
        .prefetch_related("stages")
        .first()
    )


def get_first_stage(workflow):
    if not workflow:
        return None
    return workflow.stages.order_by("order").first()


def get_stage_by_name(workflow, stage_name):
    if not workflow:
        return None
    return workflow.stages.filter(name=stage_name).first()


def validate_stage_transition(task, new_stage, role):
    if not task.workflow or not task.stage:
        return

    exists = WorkflowTransition.objects.filter(
        workflow=task.workflow,
        from_stage=task.stage,
        to_stage=new_stage,
        allowed_role=role,
    ).exists()

    if not exists:
        raise PermissionDenied("Invalid workflow stage transition.")


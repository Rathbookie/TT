from rest_framework.exceptions import PermissionDenied

from .models import (
    Workflow,
    WorkflowStage,
    WorkflowTransition,
    TransitionRule,
)


def get_default_workflow_for_tenant(tenant):
    default_workflow = (
        Workflow.objects.filter(tenant=tenant, is_default=True)
        .prefetch_related("stages")
        .first()
    )
    if default_workflow:
        return default_workflow

    published_workflow = (
        Workflow.objects.filter(tenant=tenant, is_published=True)
        .prefetch_related("stages")
        .order_by("name")
        .first()
    )
    if published_workflow:
        return published_workflow

    return (
        Workflow.objects.filter(tenant=tenant)
        .prefetch_related("stages")
        .order_by("name")
        .first()
    )


def get_first_stage(workflow):
    if not workflow:
        return None
    return workflow.stages.order_by("order").first()


def get_first_non_terminal_stage(workflow):
    if not workflow:
        return None
    return (
        workflow.stages.filter(is_terminal=False)
        .order_by("order")
        .first()
        or get_first_stage(workflow)
    )


def get_first_non_terminal_status(workflow):
    if not workflow:
        return None
    return workflow.statuses.filter(is_terminal=False).order_by("order", "name").first()


def get_stage_by_name(workflow, stage_name):
    if not workflow:
        return None
    return workflow.stages.filter(name=stage_name).first()


def validate_stage_transition(task, new_stage, role):
    if not task.workflow or not task.stage:
        return

    normalized_role = str(role or "").strip().upper().replace(" ", "_")

    # Preferred engine: TransitionRule / WorkflowStatus + proof requirements.
    rule = (
        TransitionRule.objects.filter(
            workflow=task.workflow,
            from_status__name__iexact=task.stage.name,
            to_status__name__iexact=new_stage.name,
        )
        .prefetch_related("proof_requirements")
        .first()
    )
    if rule:
        allowed_roles = [str(item).strip().upper().replace(" ", "_") for item in (rule.allowed_roles or [])]
        if allowed_roles and normalized_role not in allowed_roles:
            raise PermissionDenied("Role not allowed for this transition.")

        mandatory_requirements = rule.proof_requirements.filter(is_mandatory=True)
        if mandatory_requirements.exists():
            from core_api.models import TaskProof

            for req in mandatory_requirements:
                if not TaskProof.objects.filter(task=task, type=req.type).exists():
                    raise PermissionDenied(f"Proof required: {req.label}")
        return

    # Backward-compatible fallback engine.
    exists = WorkflowTransition.objects.filter(
        workflow=task.workflow,
        from_stage=task.stage,
        to_stage=new_stage,
        allowed_role=normalized_role,
    ).exists()

    if not exists:
        raise PermissionDenied("Invalid workflow stage transition.")

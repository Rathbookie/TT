from django.core.management.base import BaseCommand
from django.db import transaction

from context.models import Tenant
from core_api.models import Task
from core_api.workflow import ALLOWED_TRANSITIONS
from workflows.models import Workflow, WorkflowStage, WorkflowTransition


class Command(BaseCommand):
    help = "Create and assign default tenant workflows mapped from current task status FSM."

    @transaction.atomic
    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        status_names = [status for status, _ in Task.Status.choices]

        created_workflows = 0
        assigned_tasks = 0

        for tenant in tenants:
            workflow, created = Workflow.objects.get_or_create(
                tenant=tenant,
                is_default=True,
                defaults={"name": "Default Workflow"},
            )
            if created:
                created_workflows += 1

            stage_map = {}
            for idx, status_name in enumerate(status_names):
                stage, _ = WorkflowStage.objects.get_or_create(
                    workflow=workflow,
                    name=status_name,
                    defaults={
                        "order": idx,
                        "is_terminal": not bool(ALLOWED_TRANSITIONS.get(status_name)),
                    },
                )
                update_fields = []
                if stage.order != idx:
                    stage.order = idx
                    update_fields.append("order")
                terminal = not bool(ALLOWED_TRANSITIONS.get(status_name))
                if stage.is_terminal != terminal:
                    stage.is_terminal = terminal
                    update_fields.append("is_terminal")
                if update_fields:
                    stage.save(update_fields=update_fields)
                stage_map[status_name] = stage

            for from_status, transition_targets in ALLOWED_TRANSITIONS.items():
                from_stage = stage_map.get(from_status)
                if not from_stage:
                    continue

                for to_status, roles in transition_targets.items():
                    to_stage = stage_map.get(to_status)
                    if not to_stage:
                        continue

                    for role in roles:
                        WorkflowTransition.objects.get_or_create(
                            workflow=workflow,
                            from_stage=from_stage,
                            to_stage=to_stage,
                            allowed_role=role,
                        )

            tenant_tasks = Task.objects.filter(tenant=tenant)
            for task in tenant_tasks:
                target_stage = stage_map.get(task.status)
                updates = {}

                if task.workflow_id != workflow.id:
                    updates["workflow"] = workflow
                if target_stage is not None and task.stage_id != target_stage.id:
                    updates["stage"] = target_stage

                if updates:
                    for field, value in updates.items():
                        setattr(task, field, value)
                    task.save(update_fields=list(updates.keys()))
                    assigned_tasks += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed. Created {created_workflows} default workflows "
                f"and assigned {assigned_tasks} tasks."
            )
        )

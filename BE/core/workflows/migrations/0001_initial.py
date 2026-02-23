from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("context", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workflow",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("is_default", models.BooleanField(default=False)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflows",
                        to="context.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="WorkflowStage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64)),
                ("order", models.PositiveIntegerField()),
                ("is_terminal", models.BooleanField(default=False)),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stages",
                        to="workflows.workflow",
                    ),
                ),
            ],
            options={
                "ordering": ["order"],
            },
        ),
        migrations.CreateModel(
            name="WorkflowTransition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("allowed_role", models.CharField(max_length=32)),
                (
                    "from_stage",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outgoing_transitions",
                        to="workflows.workflowstage",
                    ),
                ),
                (
                    "to_stage",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="incoming_transitions",
                        to="workflows.workflowstage",
                    ),
                ),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transitions",
                        to="workflows.workflow",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="workflow",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"),
                name="uniq_workflow_name_per_tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflow",
            constraint=models.UniqueConstraint(
                condition=Q(("is_default", True)),
                fields=("tenant",),
                name="uniq_default_workflow_per_tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowstage",
            constraint=models.UniqueConstraint(
                fields=("workflow", "name"),
                name="uniq_stage_name_per_workflow",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowstage",
            constraint=models.UniqueConstraint(
                fields=("workflow", "order"),
                name="uniq_stage_order_per_workflow",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowtransition",
            constraint=models.UniqueConstraint(
                fields=("workflow", "from_stage", "to_stage", "allowed_role"),
                name="uniq_transition_per_role",
            ),
        ),
    ]

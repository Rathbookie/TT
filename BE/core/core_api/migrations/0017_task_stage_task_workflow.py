from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0001_initial"),
        ("core_api", "0016_taskattachment_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="stage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
                to="workflows.workflowstage",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="workflow",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
                to="workflows.workflow",
            ),
        ),
    ]


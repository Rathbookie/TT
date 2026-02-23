from django.contrib import admin

from .models import Workflow, WorkflowStage, WorkflowTransition


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "is_default")
    list_filter = ("tenant", "is_default")
    search_fields = ("name", "tenant__name", "tenant__slug")


@admin.register(WorkflowStage)
class WorkflowStageAdmin(admin.ModelAdmin):
    list_display = ("name", "workflow", "order", "is_terminal")
    list_filter = ("workflow__tenant", "workflow", "is_terminal")
    search_fields = ("name", "workflow__name")


@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(admin.ModelAdmin):
    list_display = ("workflow", "from_stage", "to_stage", "allowed_role")
    list_filter = ("workflow__tenant", "workflow", "allowed_role")
    search_fields = (
        "workflow__name",
        "from_stage__name",
        "to_stage__name",
        "allowed_role",
    )


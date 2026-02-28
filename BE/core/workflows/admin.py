from django.contrib import admin

from .models import (
    Workflow,
    WorkflowStage,
    WorkflowTransition,
    WorkflowPreset,
    WorkflowPresetStage,
    WorkflowPresetWidget,
    ModuleDefinition,
    TenantModule,
    DashboardConfig,
)


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


@admin.register(WorkflowPreset)
class WorkflowPresetAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "color", "is_active")
    list_filter = ("is_active", "color")
    search_fields = ("title", "slug")


@admin.register(WorkflowPresetStage)
class WorkflowPresetStageAdmin(admin.ModelAdmin):
    list_display = ("preset", "name", "order")
    list_filter = ("preset",)
    search_fields = ("preset__title", "name")


@admin.register(WorkflowPresetWidget)
class WorkflowPresetWidgetAdmin(admin.ModelAdmin):
    list_display = ("preset", "name", "order")
    list_filter = ("preset",)
    search_fields = ("preset__title", "name")


@admin.register(ModuleDefinition)
class ModuleDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "key")


@admin.register(TenantModule)
class TenantModuleAdmin(admin.ModelAdmin):
    list_display = ("tenant", "module", "is_enabled")
    list_filter = ("tenant", "is_enabled", "module__category")
    search_fields = ("tenant__name", "module__name")


@admin.register(DashboardConfig)
class DashboardConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "visibility", "is_default", "updated_at")
    list_filter = ("tenant", "visibility", "is_default")
    search_fields = ("name", "tenant__name", "tenant__slug")

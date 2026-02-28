from rest_framework import serializers

from .models import (
    Workflow,
    WorkflowStage,
    WorkflowTransition,
    WorkflowPreset,
    WorkflowPresetStage,
    WorkflowPresetWidget,
    ModuleDefinition,
    TenantModule,
)


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    from_stage_name = serializers.CharField(source="from_stage.name", read_only=True)
    to_stage_name = serializers.CharField(source="to_stage.name", read_only=True)

    class Meta:
        model = WorkflowTransition
        fields = [
            "id",
            "from_stage",
            "from_stage_name",
            "to_stage",
            "to_stage_name",
            "allowed_role",
        ]


class WorkflowStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowStage
        fields = [
            "id",
            "name",
            "order",
            "is_terminal",
            "requires_attachments",
            "requires_approval",
        ]


class WorkflowSerializer(serializers.ModelSerializer):
    stages = WorkflowStageSerializer(many=True, read_only=True)
    transitions = WorkflowTransitionSerializer(many=True, read_only=True)

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "is_default",
            "is_published",
            "published_at",
            "version",
            "stages",
            "transitions",
        ]


class WorkflowPresetStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowPresetStage
        fields = ["id", "name", "order"]


class WorkflowPresetWidgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowPresetWidget
        fields = ["id", "name", "order"]


class WorkflowPresetSerializer(serializers.ModelSerializer):
    stages = WorkflowPresetStageSerializer(many=True, read_only=True)
    widgets = WorkflowPresetWidgetSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowPreset
        fields = [
            "id",
            "slug",
            "title",
            "description",
            "color",
            "stages",
            "widgets",
        ]


class TenantModuleSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="module.id", read_only=True)
    key = serializers.CharField(source="module.key", read_only=True)
    name = serializers.CharField(source="module.name", read_only=True)
    description = serializers.CharField(source="module.description", read_only=True)
    category = serializers.CharField(source="module.category", read_only=True)

    class Meta:
        model = TenantModule
        fields = [
            "id",
            "key",
            "name",
            "description",
            "category",
            "is_enabled",
        ]


class TenantModuleUpdateSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()

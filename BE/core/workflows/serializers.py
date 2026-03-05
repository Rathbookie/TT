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
    from_stage_color = serializers.CharField(source="from_stage.color", read_only=True)
    to_stage_color = serializers.CharField(source="to_stage.color", read_only=True)

    class Meta:
        model = WorkflowTransition
        fields = [
            "id",
            "from_stage",
            "from_stage_name",
            "from_stage_color",
            "to_stage",
            "to_stage_name",
            "to_stage_color",
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
            "color",
        ]


class WorkflowSerializer(serializers.ModelSerializer):
    statuses = serializers.SerializerMethodField()
    transition_rules = serializers.SerializerMethodField()
    stages = WorkflowStageSerializer(many=True, read_only=True)
    transitions = WorkflowTransitionSerializer(many=True, read_only=True)

    def get_statuses(self, obj):
        return [
            {
                "id": status.id,
                "name": status.name,
                "order": status.order,
                "is_terminal": status.is_terminal,
                "color": status.color,
            }
            for status in obj.statuses.all().order_by("order", "name")
        ]

    def get_transition_rules(self, obj):
        rules = obj.transition_rules.select_related("from_status", "to_status").prefetch_related("proof_requirements")
        payload = []
        for rule in rules:
            payload.append(
                {
                    "id": rule.id,
                    "from_status": rule.from_status_id,
                    "from_status_name": rule.from_status.name,
                    "to_status": rule.to_status_id,
                    "to_status_name": rule.to_status.name,
                    "allowed_roles": rule.allowed_roles or [],
                    "proof_requirements": [
                        {
                            "id": req.id,
                            "type": req.type,
                            "label": req.label,
                            "is_mandatory": req.is_mandatory,
                        }
                        for req in rule.proof_requirements.all()
                    ],
                }
            )
        return payload

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "is_default",
            "is_published",
            "published_at",
            "version",
            "statuses",
            "transition_rules",
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

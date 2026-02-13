from rest_framework import serializers
from .models import Task,TaskHistory
from users.models import User


class TaskSerializer(serializers.ModelSerializer):

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "assigned_to",
            "status",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    # -------------------------
    # FIELD VALIDATION
    # -------------------------

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Title cannot be empty.")
        return value

    def validate_status(self, value):
        valid_statuses = [choice[0] for choice in Task.Status.choices]
        if value not in valid_statuses:
            raise serializers.ValidationError("Invalid status.")
        return value

    def validate_assigned_to(self, user):
        request = self.context["request"]
        current_tenant = request.user.tenant

        if user.tenant != current_tenant:
            raise serializers.ValidationError(
                "Cannot assign task outside your tenant."
            )

        return user

    # -------------------------
    # OBJECT VALIDATION
    # -------------------------

    def validate(self, attrs):
        request = self.context["request"]

        if self.instance:
            if self.instance.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "Cross-tenant modification forbidden."
                )

        return attrs

    # -------------------------
    # CREATE / UPDATE
    # -------------------------

    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context["request"]

        if instance.tenant != request.user.tenant:
            raise serializers.ValidationError(
                "Cross-tenant modification forbidden."
            )

        return super().update(instance, validated_data)

class TaskHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskHistory
        fields = [
            "id",
            "action",
            "performed_by",
            "timestamp",
            "title",
            "description",
            "status",
        ]
        read_only_fields = fields

from rest_framework import serializers
from .models import Task
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

        # Prevent cross-tenant assignment
        if hasattr(user, "tenant") and user.tenant != request.tenant:
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
            if self.instance.tenant != request.tenant:
                raise serializers.ValidationError(
                    "Cross-tenant modification forbidden."
                )

        return attrs

    # -------------------------
    # CREATE / UPDATE
    # -------------------------

    def create(self, validated_data):
        request = self.context["request"]

        return Task.objects.create(
            tenant=request.tenant,
            created_by=request.user,
            **validated_data
        )

    def update(self, instance, validated_data):
        request = self.context["request"]

        if instance.tenant != request.tenant:
            raise serializers.ValidationError(
                "Cross-tenant modification forbidden."
            )

        return super().update(instance, validated_data)

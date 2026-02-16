from rest_framework import serializers
from .models import Task, TaskHistory, TaskAttachment
from users.models import User


# ==============================
# ATTACHMENT SERIALIZER
# ==============================

class TaskAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TaskAttachment
        fields = [
            "id",
            "file",
            "original_name",
            "uploaded_by",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_by",
            "uploaded_at",
        ]

    def get_file(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


# ==============================
# USER PROJECTION SERIALIZER
# ==============================

class TaskUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


# ==============================
# TASK SERIALIZER
# ==============================

class TaskSerializer(serializers.ModelSerializer):

    assigned_to = TaskUserSerializer(read_only=True)
    created_by = TaskUserSerializer(read_only=True)

    attachments = TaskAttachmentSerializer(
        many=True,
        read_only=True
    )

    assigned_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source="assigned_to",
        write_only=True,
        required=True
    )

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "assigned_to",
            "assigned_to_id",
            "created_by",
            "status",
            "priority",
            "blocked_reason",
            "due_date",
            "version",
            "created_at",
            "updated_at",
            "attachments",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
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

        # Determine final status
        status = attrs.get("status", getattr(self.instance, "status", None))
        blocked_reason = attrs.get("blocked_reason")

        if status == Task.Status.BLOCKED and not blocked_reason:
            raise serializers.ValidationError(
                {"blocked_reason": "Blocked tasks require a reason."}
            )

        return attrs

    # -------------------------
    # UPDATE OVERRIDE
    # -------------------------

    def update(self, instance, validated_data):
        request = self.context["request"]

        if instance.tenant != request.user.tenant:
            raise serializers.ValidationError(
                "Cross-tenant modification forbidden."
            )

        # Clear blocked_reason if leaving BLOCKED
        if (
            validated_data.get("status")
            and validated_data.get("status") != Task.Status.BLOCKED
        ):
            validated_data["blocked_reason"] = None

        return super().update(instance, validated_data)


# ==============================
# TASK HISTORY SERIALIZER
# ==============================

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
            "priority",
            "due_date",
        ]
        read_only_fields = fields


# ==============================
# TENANT USER LIST SERIALIZER
# ==============================

class TenantUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

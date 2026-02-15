from rest_framework import serializers
from .models import Task,TaskHistory
from users.models import User
from .models import TaskAttachment


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



class TaskUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class TaskSerializer(serializers.ModelSerializer):

    assigned_to = TaskUserSerializer(read_only=True)
    created_by = TaskUserSerializer(read_only=True)

    attachments = TaskAttachmentSerializer(
        many=True,
        read_only=True
    )

    # Needed so POST still accepts assigned_to as ID
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


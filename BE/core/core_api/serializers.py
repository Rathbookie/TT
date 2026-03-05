"""
core_api/serializers.py

Updated to work with the new model structure:
  - Task.status is now a FK to BoardStatus (not a hardcoded TextChoices)
  - Task.assignees is now M2M (not a single assigned_to FK)
  - Task has ref_id, board, parent, start_date fields
  - TaskHistory uses status_name (snapshot string) not status FK
  - Status transition logic now works with BoardStatus names (strings)
    since transitions are enforced by name, not by enum value
"""

from rest_framework import serializers
from .models import (
    Task, TaskHistory, TaskAttachment, TaskProof,
    BoardStatus, TaskAssignee,
    Division, Section, Board,
    OrganizationProfile,
)
from users.models import User
from workflows.models import Workflow, WorkflowStage


def normalize_role_value(value):
    if value is None:
        return None
    return str(value).strip().upper().replace(" ", "_")


# =============================================================================
# STATUS TRANSITION MAP
# Now keyed by BoardStatus.name (string) instead of Task.Status enum.
# These are the default status names created by the signal.
# Custom statuses added by users bypass this map — transitions are free.
# =============================================================================

DEFAULT_ALLOWED_TRANSITIONS = {
    "Not Started":  ["In Progress", "Cancelled"],
    "In Progress":  ["Blocked", "In Review", "Cancelled"],
    "Blocked":      ["In Progress", "Cancelled"],
    "In Review":    ["Done", "In Progress", "Cancelled"],
    "Done":         ["In Progress", "Cancelled"],
    "Cancelled":    [],
}

STATUS_NAME_TO_CODE = {
    "Not Started": "NOT_STARTED",
    "In Progress": "IN_PROGRESS",
    "Blocked": "BLOCKED",
    "In Review": "WAITING_REVIEW",
    "Done": "DONE",
    "Cancelled": "CANCELLED",
}

STATUS_CODE_TO_NAME = {v: k for k, v in STATUS_NAME_TO_CODE.items()}


# =============================================================================
# USER SERIALIZER
# =============================================================================

class TaskUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


# =============================================================================
# BOARD STATUS SERIALIZER
# =============================================================================

class BoardStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoardStatus
        fields = ["id", "board", "name", "color", "order", "is_terminal", "is_cancelled", "is_default"]
        read_only_fields = ["id", "is_default"]


# =============================================================================
# ATTACHMENT SERIALIZER
# =============================================================================

class TaskAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TaskAttachment
        fields = [
            "id",
            "file",
            "original_name",
            "file_size",
            "mime_type",
            "uploaded_by",
            "uploaded_at",
            "type",
        ]
        read_only_fields = [
            "id",
            "uploaded_by",
            "uploaded_at",
            "type",
            "file_size",
            "mime_type",
        ]

    def get_file(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class TaskProofSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    submitted_by = TaskUserSerializer(read_only=True)

    class Meta:
        model = TaskProof
        fields = [
            "id",
            "type",
            "file",
            "file_url",
            "file_name",
            "text",
            "url",
            "label",
            "submitted_by",
            "submitted_at",
        ]
        read_only_fields = ["id", "submitted_by", "submitted_at"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url

    def get_file_name(self, obj):
        if not obj.file:
            return None
        return obj.file.name.split("/")[-1]

    def validate(self, attrs):
        proof_type = attrs.get("type", getattr(self.instance, "type", None))
        if proof_type == TaskProof.Type.FILE and not attrs.get("file"):
            raise serializers.ValidationError({"file": "File is required for FILE proofs."})
        if proof_type == TaskProof.Type.TEXT and not str(attrs.get("text", "")).strip():
            raise serializers.ValidationError({"text": "Text is required for TEXT proofs."})
        if proof_type == TaskProof.Type.URL and not str(attrs.get("url", "")).strip():
            raise serializers.ValidationError({"url": "URL is required for URL proofs."})
        return attrs


# =============================================================================
# TASK SERIALIZER
# =============================================================================

class TaskSerializer(serializers.ModelSerializer):

    # --- Read-only nested representations ---
    created_by  = TaskUserSerializer(read_only=True)
    assignees   = TaskUserSerializer(many=True, read_only=True)
    assigned_to = serializers.SerializerMethodField()
    status      = serializers.SerializerMethodField()
    status_detail = BoardStatusSerializer(source="status", read_only=True)
    workflow    = serializers.SerializerMethodField()
    stage       = serializers.SerializerMethodField()
    attachments = TaskAttachmentSerializer(many=True, read_only=True)
    workflow_id = serializers.PrimaryKeyRelatedField(
        queryset=Workflow.objects.all(),
        source="workflow",
        write_only=True,
        required=False,
        allow_null=True,
    )
    stage_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkflowStage.objects.all(),
        source="stage",
        write_only=True,
        required=False,
        allow_null=True,
    )

    # --- Write-only fields ---
    # Client sends status_id (PK of a BoardStatus row for this board)
    status_id = serializers.PrimaryKeyRelatedField(
        queryset=BoardStatus.objects.all(),
        source="status",
        write_only=True,
        required=False,
        allow_null=True,
    )

    # Client sends assignee_ids (list of User PKs)
    assignee_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )
    assigned_to_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True,
    )

    # Subtask count (read-only computed field)
    subtask_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "ref_id",
            "title",
            "description",
            "division",
            "board",
            "parent",
            "order",
            "status",
            "status_detail",
            "status_id",
            "priority",
            "blocked_reason",
            "due_date",
            "start_date",
            "estimated_hours",
            "assignees",
            "assigned_to",
            "assignee_ids",
            "assigned_to_id",
            "created_by",
            "workflow",
            "workflow_id",
            "stage",
            "stage_id",
            "version",
            "created_at",
            "updated_at",
            "attachments",
            "subtask_count",
        ]
        read_only_fields = [
            "id",
            "ref_id",
            "created_at",
            "updated_at",
            "created_by",
        ]

    def get_subtask_count(self, obj):
        return obj.subtasks.filter(is_deleted=False).count()

    def get_assigned_to(self, obj):
        assignee = obj.assignees.order_by("taskassignee__assigned_at").first()
        if not assignee:
            return None
        return TaskUserSerializer(assignee).data

    def get_status(self, obj):
        if not obj.status:
            return "NOT_STARTED"
        return STATUS_NAME_TO_CODE.get(obj.status.name, obj.status.name.upper().replace(" ", "_"))

    def get_workflow(self, obj):
        if not obj.workflow_id:
            return None
        return (
            Workflow.objects.filter(id=obj.workflow_id)
            .values("id", "name", "is_default")
            .first()
        )

    def get_stage(self, obj):
        if not obj.stage_id:
            return None
        return (
            WorkflowStage.objects.filter(id=obj.stage_id)
            .values("id", "name", "order", "is_terminal", "color")
            .first()
        )

    # -------------------------
    # FIELD VALIDATION
    # -------------------------

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Title cannot be empty.")
        if len(value) > 255:
            raise serializers.ValidationError("Title cannot exceed 255 characters.")
        return value

    def validate_status(self, board_status):
        """
        Ensures the chosen BoardStatus belongs to the same board as the task.
        Called when status_id is provided (source="status").
        """
        if not board_status:
            return board_status

        board = None
        if self.instance and self.instance.board_id:
            board = self.instance.board
        elif self.initial_data.get("board"):
            try:
                board_id = int(self.initial_data.get("board"))
            except (TypeError, ValueError):
                raise serializers.ValidationError("Board must be a valid integer.")
            board = Board.objects.filter(id=board_id).first()

        if board and board_status.board_id != board.id:
            raise serializers.ValidationError(
                "Status does not belong to this task's board."
            )
        return board_status

    def validate_assignee_ids(self, users):
        """Ensure all assignees belong to the same tenant."""
        request = self.context.get("request")
        if not request:
            return users
        tenant = request.user.tenant
        for user in users:
            if user.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    f"User {user.email} does not belong to your organisation."
                )
        return users

    def validate_workflow(self, workflow):
        request = self.context.get("request")
        if not request:
            return workflow
        if workflow and workflow.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError(
                "Workflow must belong to your organisation."
            )
        return workflow

    # -------------------------
    # OBJECT-LEVEL VALIDATION
    # -------------------------

    def validate(self, attrs):
        request = self.context.get("request")
        if not request:
            return attrs

        user = request.user
        active_role = normalize_role_value(request.headers.get("X-Active-Role"))

        if self.instance is None:
            board = attrs.get("board")
            if board is None:
                board = (
                    Board.objects.filter(tenant=user.tenant, is_deleted=False)
                    .order_by("order", "name")
                    .first()
                )
                if not board:
                    raise serializers.ValidationError(
                        {"board": "Board is required. Create a board first."}
                    )
                attrs["board"] = board
            if board.tenant_id != user.tenant_id:
                raise serializers.ValidationError({"board": "Board must belong to your organisation."})

        board = attrs.get("board") or getattr(self.instance, "board", None)
        division = attrs.get("division") or getattr(self.instance, "division", None)
        if board:
            board_division = board.division or (board.section.division if board.section_id else None)
            if board_division is None:
                raise serializers.ValidationError({"board": "Board must belong to a division."})
            if division and division.id != board_division.id:
                raise serializers.ValidationError(
                    {"division": "Division must match the selected board."}
                )
            attrs["division"] = board_division
        elif division and division.tenant_id != user.tenant_id:
            raise serializers.ValidationError({"division": "Division must belong to your organisation."})

        # Backward compatibility: allow assigned_to_id as a single-assignee shorthand.
        legacy_assigned_to_id = self.initial_data.get("assigned_to_id")
        if legacy_assigned_to_id not in (None, "", "null") and "assignee_ids" not in attrs:
            try:
                legacy_assigned_to_id = int(legacy_assigned_to_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError({"assigned_to_id": "assigned_to_id must be an integer."})
            assigned_user = User.objects.filter(id=legacy_assigned_to_id, tenant=user.tenant).first()
            if not assigned_user:
                raise serializers.ValidationError(
                    {"assigned_to_id": "Assigned user must belong to your organisation."}
                )
            attrs["assignee_ids"] = [assigned_user]

        # Backward compatibility: allow legacy string statuses.
        legacy_status = self.initial_data.get("status")
        if legacy_status not in (None, "", "null") and "status" not in attrs:
            legacy_status_normalized = str(legacy_status).strip().upper()
            status_name = STATUS_CODE_TO_NAME.get(legacy_status_normalized)
            board = attrs.get("board") or getattr(self.instance, "board", None)
            if not board:
                raise serializers.ValidationError({"status": "Cannot resolve status without a board."})
            if status_name is None:
                status_name = str(legacy_status).strip().replace("_", " ").title()
            status_obj = BoardStatus.objects.filter(board=board, name__iexact=status_name).first()
            if not status_obj:
                raise serializers.ValidationError(
                    {"status": f"Status '{legacy_status}' is not available on this board."}
                )
            attrs["status"] = status_obj

        if self.instance:
            # Cross-tenant guard
            if self.instance.tenant_id != user.tenant_id:
                raise serializers.ValidationError("Cross-tenant modification forbidden.")

            current_status = self.instance.status   # BoardStatus instance or None
            new_status = attrs.get("status", current_status)  # BoardStatus instance or None

            if new_status and current_status and new_status != current_status:
                current_name = current_status.name
                new_name = new_status.name

                # If current status is a default status, enforce transition rules
                if current_name in DEFAULT_ALLOWED_TRANSITIONS:
                    allowed_names = DEFAULT_ALLOWED_TRANSITIONS[current_name]

                    # Terminal "Cancelled" can never be left
                    if current_status.is_cancelled:
                        raise serializers.ValidationError(
                            {"status": "Cancelled tasks cannot be modified."}
                        )

                    # "Done" can only be reopened by ADMIN
                    if current_status.is_terminal and not current_status.is_cancelled:
                        if active_role != "ADMIN":
                            raise serializers.ValidationError(
                                {"status": "Only admin can reopen completed tasks."}
                            )

                    # Enforce transition map for default statuses
                    if new_name in DEFAULT_ALLOWED_TRANSITIONS and new_name not in allowed_names:
                        raise serializers.ValidationError(
                            {"status": f"Cannot transition from '{current_name}' to '{new_name}'."}
                        )

                    # Task receiver cannot approve (move to Done)
                    if active_role == "TASK_RECEIVER" and new_status.is_terminal and not new_status.is_cancelled:
                        raise serializers.ValidationError(
                            {"status": "Only the task creator can mark tasks as Done."}
                        )

            # Blocked reason required when moving to Blocked
            if new_status and new_status.name == "Blocked":
                blocked_reason = attrs.get(
                    "blocked_reason",
                    getattr(self.instance, "blocked_reason", None)
                )
                if not blocked_reason:
                    raise serializers.ValidationError(
                        {"blocked_reason": "A reason is required when blocking a task."}
                    )

        selected_workflow = attrs.get("workflow", getattr(self.instance, "workflow", None))
        selected_stage = attrs.get("stage", getattr(self.instance, "stage", None))
        if selected_stage and selected_workflow and selected_stage.workflow_id != selected_workflow.id:
            raise serializers.ValidationError({"stage_id": "Stage must belong to the selected workflow."})

        return attrs

    def _resolve_default_status(self, task):
        if task.status_id or not task.board_id:
            return

        default_status = (
            BoardStatus.objects.filter(board=task.board, is_default=True)
            .order_by("order")
            .first()
        )
        if default_status:
            task.status = default_status

    # -------------------------
    # CREATE / UPDATE
    # -------------------------

    def create(self, validated_data):
        assignee_users = validated_data.pop("assignee_ids", [])
        validated_data.pop("assigned_to_id", None)
        task = Task.objects.create(**validated_data)
        self._resolve_default_status(task)
        if task.status_id:
            task.save(update_fields=["status"])

        # Set assignees via through model
        request = self.context.get("request")
        assigned_by = request.user if request else None
        for user in assignee_users:
            TaskAssignee.objects.get_or_create(
                task=task,
                user=user,
                defaults={"assigned_by": assigned_by},
            )

        return task

    def update(self, instance, validated_data):
        request = self.context.get("request")

        if instance.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Cross-tenant modification forbidden.")

        assignee_users = validated_data.pop("assignee_ids", None)
        validated_data.pop("assigned_to_id", None)
        previous_status_id = instance.status_id

        # Clear blocked_reason when leaving Blocked status
        new_status = validated_data.get("status")
        if new_status and new_status.name != "Blocked":
            validated_data["blocked_reason"] = None

        task = super().update(instance, validated_data)
        self._resolve_default_status(task)
        if task.status_id != previous_status_id:
            task.save(update_fields=["status"])

        # Replace assignees if provided
        if assignee_users is not None:
            assigned_by = request.user if request else None
            TaskAssignee.objects.filter(task=task).delete()
            for user in assignee_users:
                TaskAssignee.objects.create(
                    task=task,
                    user=user,
                    assigned_by=assigned_by,
                )

        return task


# =============================================================================
# TASK HISTORY SERIALIZER
# =============================================================================

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
            "status_name",   # snapshot string — not a FK
            "priority",
            "due_date",
            "changes",
        ]
        read_only_fields = fields


# =============================================================================
# TENANT USER LIST SERIALIZER
# =============================================================================

class TenantUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


# =============================================================================
# DIVISION SERIALIZERS
# =============================================================================

class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = [
            "id", "name", "slug", "description",
            "icon", "color", "default_permission", "is_private", "order",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def validate_name(self, value):
        return value.strip()


# =============================================================================
# SECTION SERIALIZERS
# =============================================================================

class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = [
            "id", "name", "slug", "description",
            "icon", "color", "order", "division",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


# =============================================================================
# BOARD SERIALIZERS
# =============================================================================

class BoardSerializer(serializers.ModelSerializer):
    statuses = BoardStatusSerializer(many=True, read_only=True)

    class Meta:
        model = Board
        fields = [
            "id", "name", "slug", "description",
            "division", "section",
            "default_view", "icon", "color", "order",
            "statuses",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at", "statuses"]

    def validate(self, attrs):
        division = attrs.get("division", getattr(self.instance, "division", None))
        section = attrs.get("section", getattr(self.instance, "section", None))
        if division and section:
            raise serializers.ValidationError(
                "A Board cannot belong to both a Division and a Section."
            )
        if not division and not section:
            raise serializers.ValidationError(
                "A Board must belong to either a Division or a Section."
            )
        return attrs

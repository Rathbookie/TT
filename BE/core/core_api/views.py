"""
core_api/views.py

Updated for new model structure:
  - Task.status is now FK to BoardStatus (no more Task.Status enum)
  - Task.assignees is M2M (no more assigned_to single FK)
  - Task.ref_id added
  - TaskHistory uses status_name snapshot not status FK
  - Filtering updated accordingly
"""

from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status

from core_api.serializers import (
    TaskSerializer,
    TaskHistorySerializer,
    DivisionSerializer,
    SectionSerializer,
    BoardSerializer,
    BoardStatusSerializer,
    TaskProofSerializer,
    NotificationSerializer,
)
from core_api.permissions import TaskPermission, IsAdminRole
from core_api.models import (
    Task,
    TaskHistory,
    TaskAttachment,
    TaskProof,
    TaskAssignee,
    Division,
    DivisionMember,
    Section,
    Board,
    BoardStatus,
    Notification,
)
from core_api.serializers import TaskAttachmentSerializer

from users.models import UserRole
from users.models import User

from core_api.pagination import TaskPagination

from workflows.utils import (
    get_default_workflow_for_tenant,
    get_first_stage,
    get_first_non_terminal_stage,
    validate_stage_transition,
)
from core_api.notifications import (
    notify_task_assigned,
    notify_status_changed,
    notify_proof_submitted,
    notify_task_completed,
)


def normalize_role_value(value):
    if value is None:
        return None
    return str(value).strip().upper().replace(" ", "_")


def get_normalized_user_roles(user, tenant):
    raw_roles = UserRole.objects.filter(user=user, tenant=tenant).values_list(
        "role__name", flat=True
    )
    return {
        normalized
        for normalized in (normalize_role_value(role) for role in raw_roles)
        if normalized
    }


def _coerce_bool(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return fallback


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    tenant = user.tenant

    if request.method == "PATCH":
        first_name = str(request.data.get("first_name", user.first_name)).strip()
        last_name = str(request.data.get("last_name", user.last_name)).strip()
        email = str(request.data.get("email", user.email)).strip().lower()
        display_name = str(request.data.get("display_name", user.display_name or "")).strip()
        job_title = str(request.data.get("job_title", user.job_title or "")).strip()
        phone = str(request.data.get("phone", user.phone or "")).strip()
        timezone_value = str(request.data.get("timezone", user.timezone or "")).strip()
        bio = str(request.data.get("bio", user.bio or "")).strip()
        notify_task_assigned = _coerce_bool(
            request.data.get("notify_task_assigned"),
            user.notify_task_assigned,
        )
        notify_task_status_changed = _coerce_bool(
            request.data.get("notify_task_status_changed"),
            user.notify_task_status_changed,
        )
        notify_due_reminder = _coerce_bool(
            request.data.get("notify_due_reminder"),
            user.notify_due_reminder,
        )
        notify_proof_submitted = _coerce_bool(
            request.data.get("notify_proof_submitted"),
            user.notify_proof_submitted,
        )

        if (
            len(first_name) > 150
            or len(last_name) > 150
            or len(email) > 254
            or len(display_name) > 150
            or len(job_title) > 150
            or len(phone) > 30
            or len(timezone_value) > 80
        ):
            return Response(
                {"detail": "One or more profile fields exceed allowed length."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_email(email)
        except DjangoValidationError:
            return Response(
                {"detail": "Enter a valid email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email_taken = User.objects.filter(email__iexact=email).exclude(id=user.id).exists()
        if email_taken:
            return Response(
                {"detail": "This email is already in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dirty_fields = []
        if user.first_name != first_name:
            user.first_name = first_name
            dirty_fields.append("first_name")
        if user.last_name != last_name:
            user.last_name = last_name
            dirty_fields.append("last_name")
        if user.email != email:
            user.email = email
            dirty_fields.append("email")
        if user.display_name != display_name:
            user.display_name = display_name
            dirty_fields.append("display_name")
        if user.job_title != job_title:
            user.job_title = job_title
            dirty_fields.append("job_title")
        if user.phone != phone:
            user.phone = phone
            dirty_fields.append("phone")
        if user.timezone != timezone_value:
            user.timezone = timezone_value
            dirty_fields.append("timezone")
        if user.bio != bio:
            user.bio = bio
            dirty_fields.append("bio")
        if user.notify_task_assigned != notify_task_assigned:
            user.notify_task_assigned = notify_task_assigned
            dirty_fields.append("notify_task_assigned")
        if user.notify_task_status_changed != notify_task_status_changed:
            user.notify_task_status_changed = notify_task_status_changed
            dirty_fields.append("notify_task_status_changed")
        if user.notify_due_reminder != notify_due_reminder:
            user.notify_due_reminder = notify_due_reminder
            dirty_fields.append("notify_due_reminder")
        if user.notify_proof_submitted != notify_proof_submitted:
            user.notify_proof_submitted = notify_proof_submitted
            dirty_fields.append("notify_proof_submitted")
        if dirty_fields:
            user.save(update_fields=dirty_fields)

    roles = list(
        UserRole.objects.filter(user=user, tenant=tenant)
        .values_list("role__name", flat=True)
    )

    return Response({
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name or "",
        "job_title": user.job_title or "",
        "phone": user.phone or "",
        "timezone": user.timezone or "",
        "bio": user.bio or "",
        "notify_task_assigned": user.notify_task_assigned,
        "notify_task_status_changed": user.notify_task_status_changed,
        "notify_due_reminder": user.notify_due_reminder,
        "notify_proof_submitted": user.notify_proof_submitted,
        "tenant_slug": tenant.slug,
        "roles": roles,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def me_password(request):
    user = request.user
    current_password = str(request.data.get("current_password", ""))
    new_password = str(request.data.get("new_password", ""))
    confirm_password = str(request.data.get("confirm_password", ""))

    if not current_password or not new_password or not confirm_password:
        return Response(
            {"detail": "Current password, new password, and confirmation are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not user.check_password(current_password):
        return Response(
            {"detail": "Current password is incorrect."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if new_password != confirm_password:
        return Response(
            {"detail": "New password and confirmation do not match."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, user=user)
    except Exception as exc:
        first_message = str(exc)
        if hasattr(exc, "messages") and getattr(exc, "messages"):
            first_message = str(exc.messages[0])
        return Response(
            {"detail": first_message},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    return Response({"detail": "Password updated successfully."}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_list(request):
    tenant = request.user.tenant
    unread_only = str(request.query_params.get("unread", "")).strip().lower() in {"1", "true", "yes"}
    try:
        limit = int(request.query_params.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    queryset = Notification.objects.filter(tenant=tenant, user=request.user).select_related(
        "actor", "task"
    )
    if unread_only:
        queryset = queryset.filter(is_read=False)
    items = list(queryset[:limit])
    unread_count = Notification.objects.filter(
        tenant=tenant,
        user=request.user,
        is_read=False,
    ).count()
    return Response({
        "results": NotificationSerializer(items, many=True).data,
        "unread_count": unread_count,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(
        Notification.objects.filter(
            tenant=request.user.tenant,
            user=request.user,
        ),
        id=notification_id,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    return Response({"detail": "Notification marked as read."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_mark_all_read(request):
    Notification.objects.filter(
        tenant=request.user.tenant,
        user=request.user,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    return Response({"detail": "All notifications marked as read."}, status=status.HTTP_200_OK)


def _get_tenant_for_org_slug(user, org_slug):
    """
    Enforce org slug scoping against the authenticated user's tenant.
    """
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    tenant = user.tenant
    if tenant is None or tenant.slug != org_slug:
        raise PermissionDenied("Organisation slug does not match your active tenant.")
    return tenant


def _task_queryset_for_active_role(request, tenant):
    """
    Role-scoped task queryset used by slug-based task lookup endpoints.
    Includes subtasks (no parent filter).
    """
    user = request.user
    qs = (
        Task.objects.for_tenant(tenant)
        .filter(is_deleted=False)
        .select_related("status", "board", "division", "created_by", "workflow", "stage", "parent")
        .prefetch_related("assignees", "attachments")
    )

    active_role = normalize_role_value(request.headers.get("X-Active-Role"))
    user_roles = get_normalized_user_roles(user, tenant)

    if active_role not in user_roles:
        return Task.objects.none()

    if active_role == "TASK_RECEIVER":
        has_assignees = Task.assignees.through.objects.filter(task_id=OuterRef("pk"))
        qs = qs.annotate(_has_assignees=Exists(has_assignees)).filter(
            Q(assignees=user) | Q(created_by__isnull=True, _has_assignees=False)
        )
    elif active_role == "TASK_CREATOR":
        qs = qs.filter(Q(created_by=user) | Q(created_by__isnull=True))

    return qs.distinct()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_divisions(request, org_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    divisions = (
        Division.objects.for_tenant(tenant)
        .active()
        .order_by("order", "name")
    )
    return Response(DivisionSerializer(divisions, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_division_detail(request, org_slug, division_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    division = get_object_or_404(
        Division.objects.for_tenant(tenant).active(),
        slug=division_slug,
    )
    return Response(DivisionSerializer(division).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_division_sections(request, org_slug, division_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    division = get_object_or_404(
        Division.objects.for_tenant(tenant).active(),
        slug=division_slug,
    )
    sections = (
        Section.objects.for_tenant(tenant)
        .active()
        .filter(division=division)
        .select_related("division")
        .order_by("order", "name")
    )
    return Response(SectionSerializer(sections, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_division_members(request, org_slug, division_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    division = get_object_or_404(
        Division.objects.for_tenant(tenant).active(),
        slug=division_slug,
    )
    members = (
        DivisionMember.objects.filter(division=division)
        .select_related("user")
        .order_by("joined_at")
    )
    payload = [
        {
            "id": member.user_id,
            "full_name": f"{member.user.first_name} {member.user.last_name}".strip() or member.user.email,
            "email": member.user.email,
            "role": member.role,
        }
        for member in members
    ]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_division_boards(request, org_slug, division_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    division = get_object_or_404(
        Division.objects.for_tenant(tenant).active(),
        slug=division_slug,
    )
    boards = (
        Board.objects.for_tenant(tenant)
        .active()
        .filter(division=division, section__isnull=True)
        .select_related("division", "section")
        .prefetch_related("statuses")
        .order_by("order", "name")
    )
    return Response(BoardSerializer(boards, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_section_boards(request, org_slug, division_slug, section_slug):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    division = get_object_or_404(
        Division.objects.for_tenant(tenant).active(),
        slug=division_slug,
    )
    section = get_object_or_404(
        Section.objects.for_tenant(tenant).active(),
        division=division,
        slug=section_slug,
    )
    boards = (
        Board.objects.for_tenant(tenant)
        .active()
        .filter(section=section)
        .select_related("division", "section")
        .prefetch_related("statuses")
        .order_by("order", "name")
    )
    return Response(BoardSerializer(boards, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_task_by_ref(request, org_slug, task_ref):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    qs = _task_queryset_for_active_role(request, tenant)
    task = get_object_or_404(qs, ref_id__iexact=task_ref)
    return Response(TaskSerializer(task, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_subtask_by_ref(request, org_slug, task_ref, sub_ref):
    tenant = _get_tenant_for_org_slug(request.user, org_slug)
    qs = _task_queryset_for_active_role(request, tenant)
    subtask = get_object_or_404(
        qs,
        parent__ref_id__iexact=task_ref,
        ref_id__iexact=sub_ref,
    )
    return Response(TaskSerializer(subtask, context={"request": request}).data)


class TaskViewSet(ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, TaskPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = TaskPagination

    def get_queryset(self):
        user = self.request.user

        if not user or not user.is_authenticated:
            return Task.objects.none()

        tenant = user.tenant

        qs = Task.objects.for_tenant(tenant).filter(
            is_deleted=False,
            parent=None,  # top-level tasks only by default; subtasks fetched separately
        ).select_related(
            "status", "board", "division", "created_by", "workflow", "stage"
        ).prefetch_related(
            "assignees", "attachments"
        )

        active_role = normalize_role_value(self.request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(user, tenant)

        if active_role not in user_roles:
            return qs.none()

        # Role-scoped filtering
        if active_role == "TASK_RECEIVER":
            # Include explicitly assigned tasks and legacy orphaned tasks
            # (no creator + no assignees) to avoid hiding pre-migration data.
            has_assignees = Task.assignees.through.objects.filter(task_id=OuterRef("pk"))
            qs = qs.annotate(_has_assignees=Exists(has_assignees)).filter(
                Q(assignees=user) |
                Q(created_by__isnull=True, _has_assignees=False)
            ).distinct()
        elif active_role == "TASK_CREATOR":
            qs = qs.filter(
                Q(created_by=user) |
                Q(created_by__isnull=True)
            )
        # ADMIN sees all

        # Filter by board if provided
        board_id = self.request.query_params.get("board")
        if board_id:
            qs = qs.filter(board_id=board_id)

        # Filter by division (id or slug)
        division = self.request.query_params.get("division")
        if division:
            if str(division).isdigit():
                qs = qs.filter(division_id=int(division))
            else:
                qs = qs.filter(division__slug=division)

        # Filter by section (id or slug)
        section = self.request.query_params.get("section")
        if section:
            if str(section).isdigit():
                qs = qs.filter(board__section_id=int(section))
            else:
                qs = qs.filter(board__section__slug=section)

        # Filter by priority
        priority = self.request.query_params.get("priority")
        if priority:
            qs = qs.filter(priority=priority)

        # Exclude terminal statuses unless requested
        include_terminal = (
            str(self.request.query_params.get("include_terminal", "")).lower()
            in {"1", "true", "yes"}
        )
        if self.action != "list":
            include_terminal = True
        if not include_terminal:
            qs = qs.exclude(
                Q(status__is_terminal=True) | Q(stage__is_terminal=True)
            )

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        tenant = user.tenant

        active_role = normalize_role_value(self.request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(user, tenant)

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        if active_role not in ["TASK_CREATOR", "ADMIN"]:
            raise PermissionDenied("You do not have permission to create tasks.")

        save_kwargs = {
            "tenant": tenant,
            "created_by": user,
        }

        selected_workflow = serializer.validated_data.get("workflow")
        if selected_workflow:
            save_kwargs["workflow"] = selected_workflow
            save_kwargs["stage"] = get_first_stage(selected_workflow)
        else:
            default_workflow = get_default_workflow_for_tenant(tenant)
            if default_workflow:
                save_kwargs["workflow"] = default_workflow
                save_kwargs["stage"] = get_first_stage(default_workflow)

        task = serializer.save(**save_kwargs)

        TaskHistory.objects.create(
            tenant=task.tenant,
            task=task,
            action=TaskHistory.Action.CREATED,
            performed_by=user,
            title=task.title,
            description=task.description,
            status_name=task.status.name if task.status else "",
            priority=task.priority,
            due_date=task.due_date,
        )

        assigned_users = list(task.assignees.all())
        if assigned_users:
            notify_task_assigned(
                task=task,
                actor=user,
                recipients=assigned_users,
            )

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            instance = self.get_object()
            old_assignee_ids = set(instance.assignees.values_list("id", flat=True))

            if instance.tenant_id != request.user.tenant_id:
                raise PermissionDenied("Cross-tenant modification forbidden.")

            active_role = normalize_role_value(request.headers.get("X-Active-Role"))
            user_roles = get_normalized_user_roles(request.user, request.user.tenant)

            if active_role not in user_roles:
                raise PermissionDenied("Invalid active role.")

            if instance.is_deleted:
                raise PermissionDenied("Cannot modify deleted task.")

            # Version check (optimistic locking)
            client_version = request.data.get("version")
            if client_version is None:
                raise ValidationError({"version": "Version is required."})
            try:
                client_version = int(client_version)
            except (TypeError, ValueError):
                raise ValidationError({"version": "Version must be a valid integer."})

            if client_version != instance.version:
                return Response(
                    {"detail": "Conflict detected. Task was modified by another user."},
                    status=status.HTTP_409_CONFLICT,
                )

            # Receiver field restrictions
            update_data = request.data.copy()
            if active_role == "TASK_RECEIVER":
                allowed_fields = {"status_id", "status", "stage_id", "blocked_reason", "version"}
                for field in update_data.keys():
                    if field not in allowed_fields:
                        raise PermissionDenied(
                            "Task receivers can only update status fields."
                        )

            # Creator ownership
            if active_role == "TASK_CREATOR":
                if instance.created_by_id != request.user.id:
                    raise PermissionDenied("You can only modify tasks you created.")

            # Snapshot old status name for history
            old_status_name = instance.status.name if instance.status else ""

            # Workflow switching strategy:
            # reset to the first non-terminal stage of the selected workflow.
            new_workflow_id = update_data.get("workflow_id")
            if new_workflow_id not in (None, "", "null"):
                try:
                    new_workflow_id = int(new_workflow_id)
                except (TypeError, ValueError):
                    raise ValidationError({"workflow_id": "workflow_id must be a valid integer."})

                if new_workflow_id != (instance.workflow_id or 0):
                    target_workflow = instance.tenant.workflows.filter(id=new_workflow_id).first()
                    if target_workflow is None:
                        raise ValidationError({"workflow_id": "Workflow does not belong to this tenant."})
                    target_stage = get_first_non_terminal_stage(target_workflow)
                    update_data["stage_id"] = target_stage.id if target_stage else None

            # FSM enforcement
            # Workflow stage transitions are validated only when stage_id is provided and workflow is unchanged.
            new_stage_id = update_data.get("stage_id")
            workflow_id_for_transition = update_data.get("workflow_id", instance.workflow_id)
            if workflow_id_for_transition in ("", None, "null"):
                workflow_id_for_transition = instance.workflow_id
            try:
                workflow_id_for_transition = int(workflow_id_for_transition)
            except (TypeError, ValueError):
                workflow_id_for_transition = instance.workflow_id
            if (
                new_stage_id
                and instance.workflow_id
                and instance.stage_id
                and workflow_id_for_transition == instance.workflow_id
            ):
                try:
                    new_stage_id = int(new_stage_id)
                except (TypeError, ValueError):
                    raise ValidationError({"stage_id": "stage_id must be a valid integer."})

                if new_stage_id != instance.stage_id:
                    new_stage = instance.workflow.stages.filter(id=new_stage_id).first()
                    if new_stage is None:
                        raise ValidationError({"stage_id": "Stage does not belong to this workflow."})
                    validate_stage_transition(instance, new_stage, active_role)

            # Save
            serializer = self.get_serializer(
                instance,
                data=update_data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            task = serializer.save(
                updated_by=request.user,
                version=F("version") + 1,
            )
            task.refresh_from_db()
            new_assignees = list(task.assignees.all())
            new_assignee_ids = {u.id for u in new_assignees}

            # History action classification
            new_status_name = task.status.name if task.status else ""
            history_action = TaskHistory.Action.UPDATED

            if old_status_name != new_status_name:
                if old_status_name == "In Progress" and new_status_name == "In Review":
                    history_action = TaskHistory.Action.SUBMITTED
                elif old_status_name == "In Review" and new_status_name == "Done":
                    history_action = TaskHistory.Action.APPROVED
                elif old_status_name == "In Review" and new_status_name == "In Progress":
                    history_action = TaskHistory.Action.REJECTED

            # Build changes diff
            changes = {}
            if old_status_name != new_status_name:
                changes["status"] = {"from": old_status_name, "to": new_status_name}

            TaskHistory.objects.create(
                tenant=task.tenant,
                task=task,
                action=history_action,
                performed_by=request.user,
                title=task.title,
                description=task.description,
                status_name=new_status_name,
                priority=task.priority,
                due_date=task.due_date,
                changes=changes,
            )

            if old_status_name != new_status_name:
                recipients_by_id = {}
                if task.created_by_id:
                    recipients_by_id[task.created_by_id] = task.created_by
                for assignee in new_assignees:
                    recipients_by_id[assignee.id] = assignee
                notify_status_changed(
                    task=task,
                    actor=request.user,
                    from_status=old_status_name,
                    to_status=new_status_name,
                    recipients=list(recipients_by_id.values()),
                )

                became_terminal_done = bool(task.status and task.status.is_terminal and not task.status.is_cancelled)
                if became_terminal_done:
                    notify_task_completed(
                        task=task,
                        actor=request.user,
                        recipients=new_assignees,
                    )

            added_assignee_ids = new_assignee_ids - old_assignee_ids
            if added_assignee_ids:
                recipients = [u for u in new_assignees if u.id in added_assignee_ids]
                notify_task_assigned(
                    task=task,
                    actor=request.user,
                    recipients=recipients,
                )

            return Response(self.get_serializer(task).data)

    def perform_destroy(self, instance):
        active_role = normalize_role_value(self.request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(self.request.user, self.request.user.tenant)

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        if active_role == "TASK_RECEIVER":
            raise PermissionDenied("Task receivers cannot delete tasks.")

        if active_role == "TASK_CREATOR" and instance.created_by_id != self.request.user.id:
            raise PermissionDenied("You can only delete tasks you created.")

        if instance.tenant_id != self.request.user.tenant_id:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        if instance.is_deleted:
            return

        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save()

        TaskHistory.objects.create(
            tenant=instance.tenant,
            task=instance,
            action=TaskHistory.Action.SOFT_DELETED,
            performed_by=self.request.user,
            title=instance.title,
            description=instance.description,
            status_name=instance.status.name if instance.status else "",
            priority=instance.priority,
            due_date=instance.due_date,
        )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        task = self.get_object()

        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant access forbidden.")

        queryset = TaskHistory.objects.filter(
            task=task,
            tenant=request.user.tenant,
        ).order_by("-timestamp")

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TaskHistorySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = TaskHistorySerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="subtasks")
    def subtasks(self, request, pk=None):
        """Returns all subtasks for a given task."""
        task = self.get_object()

        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant access forbidden.")

        qs = Task.objects.filter(
            parent=task,
            is_deleted=False,
        ).select_related("status", "created_by").prefetch_related("assignees")

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="attachments",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_attachment(self, request, pk=None):
        task = self.get_object()

        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant upload forbidden.")

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        attachment_type = (
            TaskAttachment.Type.SUBMISSION
            if active_role == "TASK_RECEIVER"
            else TaskAttachment.Type.REQUIREMENT
        )

        if active_role == "TASK_RECEIVER":
            if not task.status or task.status.name != "In Progress":
                raise PermissionDenied(
                    "You can only upload files while the task is In Progress."
                )

        if "file" not in request.FILES:
            return Response(
                {"detail": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES["file"]

        attachment = TaskAttachment.objects.create(
            tenant=request.user.tenant,
            task=task,
            uploaded_by=request.user,
            file=uploaded_file,
            original_name=uploaded_file.name,
            file_size=uploaded_file.size,
            mime_type=uploaded_file.content_type,
            type=attachment_type,
        )

        serializer = TaskAttachmentSerializer(
            attachment,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["delete"],
        url_path="attachments/(?P<attachment_id>[^/.]+)",
    )
    def delete_attachment(self, request, pk=None, attachment_id=None):
        task = self.get_object()

        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        try:
            attachment = TaskAttachment.objects.get(
                id=attachment_id,
                task=task,
                tenant=request.user.tenant,
            )
        except TaskAttachment.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if active_role == "TASK_RECEIVER":
            if not task.status or task.status.name != "In Progress":
                raise PermissionDenied(
                    "Task receivers can only delete files while task is In Progress."
                )
            if attachment.type != TaskAttachment.Type.SUBMISSION:
                raise PermissionDenied("Task receivers can only delete submission files.")
            if attachment.uploaded_by_id != request.user.id:
                raise PermissionDenied("You can only delete files you uploaded.")

        if active_role == "TASK_CREATOR":
            if attachment.type != TaskAttachment.Type.REQUIREMENT:
                raise PermissionDenied("Task creators can only delete requirement files.")

        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="proofs",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def proofs(self, request, pk=None):
        task = self.get_object()
        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant access forbidden.")

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)
        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        if request.method.lower() == "get":
            proofs = TaskProof.objects.filter(task=task, tenant=request.user.tenant)
            serializer = TaskProofSerializer(proofs, many=True, context={"request": request})
            return Response(serializer.data)

        is_terminal_task = bool(task.stage and task.stage.is_terminal) or bool(task.status and task.status.is_terminal)
        if is_terminal_task:
            raise PermissionDenied("Proofs cannot be added once task is terminal.")

        serializer = TaskProofSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        proof = serializer.save(
            task=task,
            tenant=request.user.tenant,
            submitted_by=request.user,
        )
        recipients_by_id = {}
        if task.created_by_id:
            recipients_by_id[task.created_by_id] = task.created_by
        for assignee in task.assignees.all():
            recipients_by_id[assignee.id] = assignee
        notify_proof_submitted(
            task=task,
            actor=request.user,
            recipients=list(recipients_by_id.values()),
        )
        return Response(TaskProofSerializer(proof, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["delete"],
        url_path="proofs/(?P<proof_id>[^/.]+)",
    )
    def delete_proof(self, request, pk=None, proof_id=None):
        task = self.get_object()
        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        proof = TaskProof.objects.filter(
            id=proof_id,
            task=task,
            tenant=request.user.tenant,
        ).first()
        if not proof:
            return Response(status=status.HTTP_404_NOT_FOUND)

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)
        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")
        if active_role not in {"ADMIN", "TASK_CREATOR"} and proof.submitted_by_id != request.user.id:
            raise PermissionDenied("You can only delete proofs you submitted.")

        proof.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="assignees")
    def add_assignee(self, request, pk=None):
        task = self.get_object()
        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant update forbidden.")

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)
        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")
        if active_role not in {"ADMIN", "TASK_CREATOR"}:
            raise PermissionDenied("Only admin or task creator can add assignees.")

        user_id = request.data.get("user_id")
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise ValidationError({"user_id": "user_id must be a valid integer."})

        assignee = request.user.tenant.users.filter(id=user_id).first()
        if not assignee:
            raise ValidationError({"user_id": "User does not belong to this tenant."})

        _, created = TaskAssignee.objects.get_or_create(
            task=task,
            user=assignee,
            defaults={"assigned_by": request.user},
        )
        task.refresh_from_db()
        if created:
            notify_task_assigned(
                task=task,
                actor=request.user,
                recipients=[assignee],
            )
        return Response(self.get_serializer(task).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["delete"], url_path=r"assignees/(?P<user_id>[^/.]+)")
    def remove_assignee(self, request, pk=None, user_id=None):
        task = self.get_object()
        if task.tenant_id != request.user.tenant_id:
            raise PermissionDenied("Cross-tenant update forbidden.")

        active_role = normalize_role_value(request.headers.get("X-Active-Role"))
        user_roles = get_normalized_user_roles(request.user, request.user.tenant)
        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")
        if active_role not in {"ADMIN", "TASK_CREATOR"}:
            raise PermissionDenied("Only admin or task creator can remove assignees.")

        TaskAssignee.objects.filter(task=task, user_id=user_id).delete()
        task.refresh_from_db()
        return Response(self.get_serializer(task).data, status=status.HTTP_200_OK)


class TenantHierarchyViewSet(ModelViewSet):
    """Shared tenant scoping + admin-write behavior for hierarchy resources."""

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated()]


class DivisionViewSet(TenantHierarchyViewSet):
    serializer_class = DivisionSerializer
    queryset = Division.objects.none()

    def get_queryset(self):
        return Division.objects.for_tenant(self.request.user.tenant).active().order_by("order", "name")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant, created_by=self.request.user)


class SectionViewSet(TenantHierarchyViewSet):
    serializer_class = SectionSerializer
    queryset = Section.objects.none()

    def get_queryset(self):
        return (
            Section.objects.for_tenant(self.request.user.tenant)
            .active()
            .select_related("division")
            .order_by("order", "name")
        )

    def perform_create(self, serializer):
        division = serializer.validated_data["division"]
        if division.tenant_id != self.request.user.tenant_id:
            raise ValidationError({"division": "Division must belong to your tenant."})
        serializer.save(tenant=self.request.user.tenant, created_by=self.request.user)


class BoardViewSet(TenantHierarchyViewSet):
    serializer_class = BoardSerializer
    queryset = Board.objects.none()

    def get_queryset(self):
        return (
            Board.objects.for_tenant(self.request.user.tenant)
            .active()
            .select_related("division", "section")
            .prefetch_related("statuses")
            .order_by("order", "name")
        )

    def _validate_parent_scope(self, serializer):
        division = serializer.validated_data.get("division")
        section = serializer.validated_data.get("section")
        if division and division.tenant_id != self.request.user.tenant_id:
            raise ValidationError({"division": "Division must belong to your tenant."})
        if section and section.tenant_id != self.request.user.tenant_id:
            raise ValidationError({"section": "Section must belong to your tenant."})

    def perform_create(self, serializer):
        self._validate_parent_scope(serializer)
        serializer.save(tenant=self.request.user.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        self._validate_parent_scope(serializer)
        serializer.save()


class TaskStatusViewSet(TenantHierarchyViewSet):
    serializer_class = BoardStatusSerializer
    queryset = BoardStatus.objects.none()

    def get_queryset(self):
        return (
            BoardStatus.objects.filter(board__tenant=self.request.user.tenant)
            .select_related("board")
            .order_by("board_id", "order")
        )

    def perform_create(self, serializer):
        board = serializer.validated_data["board"]
        if board.tenant_id != self.request.user.tenant_id:
            raise ValidationError({"board": "Board must belong to your tenant."})
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.is_default:
            raise ValidationError({"detail": "Default statuses cannot be modified."})
        board = serializer.validated_data.get("board", instance.board)
        if board.tenant_id != self.request.user.tenant_id:
            raise ValidationError({"board": "Board must belong to your tenant."})
        serializer.save()

    def perform_destroy(self, instance):
        if instance.is_default:
            raise ValidationError({"detail": "Default statuses cannot be deleted."})
        if instance.board.tenant_id != self.request.user.tenant_id:
            raise PermissionDenied("Cross-tenant deletion forbidden.")
        instance.delete()

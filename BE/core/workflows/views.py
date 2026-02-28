from django.db import transaction
from django.db.models import F
from django.db.models import Count
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from .models import (
    Workflow,
    WorkflowStage,
    WorkflowTransition,
    WorkflowPreset,
    ModuleDefinition,
    TenantModule,
)
from .serializers import (
    WorkflowSerializer,
    WorkflowPresetSerializer,
    TenantModuleSerializer,
    TenantModuleUpdateSerializer,
)
from core_api.permissions import IsAdminRole
from users.models import Role
from core_api.models import Task


class WorkflowViewSet(ModelViewSet):
    serializer_class = WorkflowSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        tenant = self.request.user.tenant
        return (
            Workflow.objects.filter(tenant=tenant)
            .prefetch_related(
                "stages",
                "transitions",
                "transitions__from_stage",
                "transitions__to_stage",
            )
            .order_by("name")
        )

    def get_permissions(self):
        if self.action in {"create", "builder", "destroy", "publish"}:
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated()]

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use /builder endpoint for workflow updates."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        workflow = self.get_object()

        if workflow.is_default:
            return Response(
                {"detail": "Default workflow cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        active_tasks = workflow.tasks.filter(is_deleted=False).count()
        if active_tasks:
            return Response(
                {
                    "detail": "Cannot delete workflow with active tasks.",
                    "active_task_count": active_tasks,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        workflow.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs):
        is_admin = request.user.user_roles.filter(
            tenant=request.user.tenant,
            role__name__iexact=Role.ADMIN,
        ).exists()
        if not is_admin:
            return Response(
                {"detail": "Only admin can create workflows."},
                status=status.HTTP_403_FORBIDDEN,
            )

        base_name = str(request.data.get("name", "")).strip() or "New Workflow"
        name = base_name
        idx = 2
        while Workflow.objects.filter(tenant=request.user.tenant, name=name).exists():
            name = f"{base_name} {idx}"
            idx += 1

        workflow = Workflow.objects.create(
            tenant=request.user.tenant,
            name=name,
            is_default=False,
        )
        WorkflowStage.objects.create(
            workflow=workflow,
            name="Stage 1",
            order=0,
            is_terminal=False,
        )

        serializer = self.get_serializer(workflow)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch"],
        url_path="builder",
        permission_classes=[IsAuthenticated, IsAdminRole],
    )
    @transaction.atomic
    def builder(self, request, pk=None):
        workflow = self.get_object()
        dirty = False

        client_version = request.data.get("version")
        if client_version is not None:
            try:
                client_version = int(client_version)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid workflow version."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if client_version != workflow.version:
                return Response(
                    {
                        "detail": "Workflow has changed. Refresh and retry.",
                        "current_version": workflow.version,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        name = request.data.get("name")
        if isinstance(name, str) and name.strip() and workflow.name != name.strip():
            workflow.name = name.strip()
            workflow.save(update_fields=["name"])
            dirty = True

        stages_data = request.data.get("stages")
        if not isinstance(stages_data, list):
            serializer = self.get_serializer(workflow)
            return Response(serializer.data, status=status.HTTP_200_OK)

        existing_stage_ids = set(
            workflow.stages.values_list("id", flat=True)
        )
        seen_stage_ids = set()

        for idx, stage_data in enumerate(stages_data):
            if not isinstance(stage_data, dict):
                continue

            stage_id = stage_data.get("id")
            stage_name = str(stage_data.get("name", "")).strip() or f"Stage {idx + 1}"
            is_terminal = bool(stage_data.get("is_terminal", False))
            requires_attachments = bool(stage_data.get("requires_attachments", False))
            requires_approval = bool(stage_data.get("requires_approval", False))

            stage = None
            try:
                parsed_id = int(stage_id)
            except (TypeError, ValueError):
                parsed_id = None

            if parsed_id and parsed_id in existing_stage_ids:
                stage = workflow.stages.filter(id=parsed_id).first()

            if stage is None:
                stage = workflow.stages.create(
                    name=stage_name,
                    order=idx,
                    is_terminal=is_terminal,
                    requires_attachments=requires_attachments,
                    requires_approval=requires_approval,
                )
                dirty = True
            else:
                stage_dirty = False
                if stage.name != stage_name:
                    stage.name = stage_name
                    stage_dirty = True
                if stage.order != idx:
                    stage.order = idx
                    stage_dirty = True
                if stage.is_terminal != is_terminal:
                    stage.is_terminal = is_terminal
                    stage_dirty = True
                if stage.requires_attachments != requires_attachments:
                    stage.requires_attachments = requires_attachments
                    stage_dirty = True
                if stage.requires_approval != requires_approval:
                    stage.requires_approval = requires_approval
                    stage_dirty = True
                if stage_dirty:
                    dirty = True
                stage.name = stage_name
                stage.order = idx
                stage.is_terminal = is_terminal
                stage.requires_attachments = requires_attachments
                stage.requires_approval = requires_approval
                stage.save(
                    update_fields=[
                        "name",
                        "order",
                        "is_terminal",
                        "requires_attachments",
                        "requires_approval",
                    ]
                )

            seen_stage_ids.add(stage.id)

        stages_to_delete = existing_stage_ids - seen_stage_ids
        if stages_to_delete:
            blocking_counts = (
                Task.objects.filter(
                    workflow=workflow,
                    is_deleted=False,
                    stage_id__in=stages_to_delete,
                )
                .values("stage_id")
                .annotate(task_count=Count("id"))
            )
            block_map = {}
            for row in blocking_counts:
                stage_id = row.get("stage_id")
                if stage_id is None:
                    continue
                block_map[stage_id] = block_map.get(stage_id, 0) + 1

            if block_map:
                blocked_stages = list(
                    workflow.stages.filter(id__in=block_map.keys()).values("id", "name")
                )
                for stage in blocked_stages:
                    stage["task_count"] = block_map.get(stage["id"], 0)
                return Response(
                    {
                        "detail": "Cannot delete stages that still have active tasks.",
                        "blocked_stages": blocked_stages,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            workflow.stages.filter(id__in=stages_to_delete).delete()
            dirty = True

        transitions_data = request.data.get("transitions")
        if isinstance(transitions_data, list):
            current_stage_ids = set(workflow.stages.values_list("id", flat=True))
            workflow.transitions.all().delete()
            dirty = True
            for transition_data in transitions_data:
                if not isinstance(transition_data, dict):
                    continue
                try:
                    from_stage_id = int(transition_data.get("from_stage"))
                    to_stage_id = int(transition_data.get("to_stage"))
                except (TypeError, ValueError):
                    continue

                allowed_role = str(transition_data.get("allowed_role", "")).strip()
                if not allowed_role:
                    continue

                if from_stage_id not in current_stage_ids or to_stage_id not in current_stage_ids:
                    continue

                WorkflowTransition.objects.create(
                    workflow=workflow,
                    from_stage_id=from_stage_id,
                    to_stage_id=to_stage_id,
                    allowed_role=allowed_role,
                )

        if dirty:
            workflow.version = F("version") + 1
            workflow.save(update_fields=["version"])
            workflow.refresh_from_db(fields=["version"])

        serializer = self.get_serializer(workflow)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, IsAdminRole],
    )
    @transaction.atomic
    def publish(self, request, pk=None):
        workflow = self.get_object()

        client_version = request.data.get("version")
        if client_version is not None:
            try:
                client_version = int(client_version)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid workflow version."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if client_version != workflow.version:
                return Response(
                    {
                        "detail": "Workflow has changed. Refresh and retry.",
                        "current_version": workflow.version,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        workflow.is_published = True
        workflow.published_at = timezone.now()
        workflow.version = F("version") + 1
        workflow.save(update_fields=["is_published", "published_at", "version"])
        workflow.refresh_from_db(fields=["version", "is_published", "published_at"])

        serializer = self.get_serializer(workflow)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkflowPresetViewSet(ModelViewSet):
    serializer_class = WorkflowPresetSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        return (
            WorkflowPreset.objects.filter(is_active=True)
            .prefetch_related("stages", "widgets")
            .order_by("title")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="apply",
        permission_classes=[IsAuthenticated, IsAdminRole],
    )
    @transaction.atomic
    def apply(self, request, pk=None):
        preset = self.get_object()
        tenant = request.user.tenant

        base_name = preset.title
        name = base_name
        idx = 2
        while Workflow.objects.filter(tenant=tenant, name=name).exists():
            name = f"{base_name} {idx}"
            idx += 1

        is_default = not Workflow.objects.filter(
            tenant=tenant,
            is_default=True,
        ).exists()

        workflow = Workflow.objects.create(
            tenant=tenant,
            name=name,
            is_default=is_default,
        )

        role_names = [Role.ADMIN, Role.TASK_CREATOR, Role.TASK_RECEIVER]
        created_stages = []
        preset_stages = list(preset.stages.order_by("order"))
        for idx, preset_stage in enumerate(preset_stages):
            created_stages.append(
                WorkflowStage.objects.create(
                    workflow=workflow,
                    name=preset_stage.name,
                    order=idx,
                    is_terminal=idx == len(preset_stages) - 1,
                )
            )

        for idx in range(len(created_stages) - 1):
            from_stage = created_stages[idx]
            to_stage = created_stages[idx + 1]
            for role_name in role_names:
                WorkflowTransition.objects.create(
                    workflow=workflow,
                    from_stage=from_stage,
                    to_stage=to_stage,
                    allowed_role=role_name,
                )

        serializer = WorkflowSerializer(workflow)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TenantModuleViewSet(ModelViewSet):
    serializer_class = TenantModuleSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        tenant = self.request.user.tenant
        modules = ModuleDefinition.objects.filter(is_active=True)

        # Ensure tenant module state rows exist for all active modules.
        for module in modules:
            TenantModule.objects.get_or_create(
                tenant=tenant,
                module=module,
                defaults={"is_enabled": False},
            )

        return (
            TenantModule.objects.filter(tenant=tenant, module__is_active=True)
            .select_related("module")
            .order_by("module__name")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        is_admin = request.user.user_roles.filter(
            tenant=request.user.tenant,
            role__name__iexact=Role.ADMIN,
        ).exists()
        if not is_admin:
            return Response(
                {"detail": "Only admin can update modules."},
                status=status.HTTP_403_FORBIDDEN,
            )

        instance = self.get_object()
        serializer = TenantModuleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.is_enabled = serializer.validated_data["is_enabled"]
        instance.save(update_fields=["is_enabled"])
        return Response(TenantModuleSerializer(instance).data)

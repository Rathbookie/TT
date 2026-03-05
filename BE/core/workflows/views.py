import re
from collections import Counter

from django.db import transaction
from django.db import IntegrityError
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
    WorkflowStatus,
    TransitionRule,
    ProofRequirement,
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

DEFAULT_STAGE_COLORS = [
    "#6B7280",  # gray
    "#2563EB",  # blue
    "#F59E0B",  # amber
    "#0EA5E9",  # cyan
    "#10B981",  # emerald
    "#EF4444",  # red
]
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_color(value, fallback):
    candidate = str(value or "").strip().upper()
    if HEX_COLOR_RE.match(candidate):
        return candidate
    return fallback


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
                "statuses",
                "transition_rules",
                "transition_rules__proof_requirements",
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

        has_default = Workflow.objects.filter(
            tenant=request.user.tenant,
            is_default=True,
        ).exists()

        workflow = Workflow.objects.create(
            tenant=request.user.tenant,
            name=name,
            is_default=not has_default,
        )
        WorkflowStage.objects.create(
            workflow=workflow,
            name="Stage 1",
            order=0,
            is_terminal=False,
            color=DEFAULT_STAGE_COLORS[0],
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

        stage_names = []
        for idx, stage_data in enumerate(stages_data):
            if not isinstance(stage_data, dict):
                continue
            stage_name = str(stage_data.get("name", "")).strip() or f"Stage {idx + 1}"
            stage_names.append(stage_name.lower())
        duplicate_stage_names = [name for name, count in Counter(stage_names).items() if count > 1]
        if duplicate_stage_names:
            duplicates = ", ".join(sorted(set(duplicate_stage_names)))
            return Response(
                {"detail": f"Stage names must be unique. Duplicate values: {duplicates}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_stages = list(workflow.stages.all())
        existing_stage_map = {stage.id: stage for stage in existing_stages}
        existing_stage_ids = set(existing_stage_map.keys())
        seen_stage_ids = set()

        needs_stage_reorder = False
        for idx, stage_data in enumerate(stages_data):
            if not isinstance(stage_data, dict):
                continue
            try:
                parsed_id = int(stage_data.get("id"))
            except (TypeError, ValueError):
                continue
            stage_obj = existing_stage_map.get(parsed_id)
            if stage_obj and stage_obj.order != idx:
                needs_stage_reorder = True
                break

        if needs_stage_reorder and existing_stages:
            temp_base = max(len(stages_data), len(existing_stages)) + 1000
            for temp_idx, stage in enumerate(sorted(existing_stages, key=lambda item: item.order)):
                stage.order = temp_base + temp_idx
                stage.save(update_fields=["order"])

        stage_names_by_id = {}
        stage_name_conflict_risk = False
        for idx, stage_data in enumerate(stages_data):
            if not isinstance(stage_data, dict):
                continue
            try:
                parsed_id = int(stage_data.get("id"))
            except (TypeError, ValueError):
                continue
            stage_obj = existing_stage_map.get(parsed_id)
            if not stage_obj:
                continue
            next_name = str(stage_data.get("name", "")).strip() or f"Stage {idx + 1}"
            stage_names_by_id[parsed_id] = next_name
            if stage_obj.name != next_name:
                stage_name_conflict_risk = True

        if stage_name_conflict_risk and existing_stages:
            for stage in existing_stages:
                stage.name = f"__tmp_stage_{stage.id}_{workflow.id}__"
                stage.save(update_fields=["name"])

        for idx, stage_data in enumerate(stages_data):
            if not isinstance(stage_data, dict):
                continue

            stage_id = stage_data.get("id")
            stage_name = str(stage_data.get("name", "")).strip() or f"Stage {idx + 1}"
            is_terminal = bool(stage_data.get("is_terminal", False))
            requires_attachments = bool(stage_data.get("requires_attachments", False))
            requires_approval = bool(stage_data.get("requires_approval", False))
            stage_color = normalize_color(
                stage_data.get("color"),
                DEFAULT_STAGE_COLORS[idx % len(DEFAULT_STAGE_COLORS)],
            )

            stage = None
            try:
                parsed_id = int(stage_id)
            except (TypeError, ValueError):
                parsed_id = None

            if parsed_id and parsed_id in existing_stage_ids:
                stage = existing_stage_map.get(parsed_id)

            if stage is None:
                try:
                    stage = workflow.stages.create(
                        name=stage_name,
                        order=idx,
                        is_terminal=is_terminal,
                        requires_attachments=requires_attachments,
                        requires_approval=requires_approval,
                        color=stage_color,
                    )
                except IntegrityError:
                    return Response(
                        {"detail": f"Stage name '{stage_name}' already exists in this workflow."},
                        status=status.HTTP_400_BAD_REQUEST,
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
                if stage.color != stage_color:
                    stage.color = stage_color
                    stage_dirty = True
                if stage_dirty:
                    dirty = True
                stage.name = stage_name
                stage.order = idx
                stage.is_terminal = is_terminal
                stage.requires_attachments = requires_attachments
                stage.requires_approval = requires_approval
                stage.color = stage_color
                try:
                    stage.save(
                        update_fields=[
                            "name",
                            "order",
                            "is_terminal",
                            "requires_attachments",
                            "requires_approval",
                            "color",
                        ]
                    )
                except IntegrityError:
                    return Response(
                        {"detail": f"Stage name '{stage_name}' already exists in this workflow."},
                        status=status.HTTP_400_BAD_REQUEST,
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

        statuses_data = request.data.get("statuses")
        if not isinstance(statuses_data, list) or len(statuses_data) == 0:
            statuses_data = [
                {
                    "name": stage.name,
                    "order": stage.order,
                    "is_terminal": stage.is_terminal,
                    "color": stage.color,
                }
                for stage in workflow.stages.order_by("order")
            ]

        if isinstance(statuses_data, list):
            status_names = []
            for idx, status_data in enumerate(statuses_data):
                if not isinstance(status_data, dict):
                    continue
                status_name = str(status_data.get("name", "")).strip() or f"Status {idx + 1}"
                status_names.append(status_name.lower())
            duplicate_status_names = [name for name, count in Counter(status_names).items() if count > 1]
            if duplicate_status_names:
                duplicates = ", ".join(sorted(set(duplicate_status_names)))
                return Response(
                    {"detail": f"Status names must be unique. Duplicate values: {duplicates}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_statuses = list(workflow.statuses.all())
            existing_status_map = {status.id: status for status in existing_statuses}
            existing_status_ids = set(existing_status_map.keys())
            seen_status_ids = set()

            needs_status_reorder = False
            for idx, status_data in enumerate(statuses_data):
                if not isinstance(status_data, dict):
                    continue
                try:
                    parsed_id = int(status_data.get("id"))
                except (TypeError, ValueError):
                    continue
                status_obj = existing_status_map.get(parsed_id)
                if status_obj and status_obj.order != idx:
                    needs_status_reorder = True
                    break

            if needs_status_reorder and existing_statuses:
                temp_base = max(len(statuses_data), len(existing_statuses)) + 1000
                for temp_idx, status_obj in enumerate(
                    sorted(existing_statuses, key=lambda item: item.order)
                ):
                    status_obj.order = temp_base + temp_idx
                    status_obj.save(update_fields=["order"])

            status_names_by_id = {}
            status_name_conflict_risk = False
            for idx, status_data in enumerate(statuses_data):
                if not isinstance(status_data, dict):
                    continue
                try:
                    parsed_id = int(status_data.get("id"))
                except (TypeError, ValueError):
                    continue
                status_obj = existing_status_map.get(parsed_id)
                if not status_obj:
                    continue
                next_name = str(status_data.get("name", "")).strip() or f"Status {idx + 1}"
                status_names_by_id[parsed_id] = next_name
                if status_obj.name != next_name:
                    status_name_conflict_risk = True

            if status_name_conflict_risk and existing_statuses:
                for status_obj in existing_statuses:
                    status_obj.name = f"__tmp_status_{status_obj.id}_{workflow.id}__"
                    status_obj.save(update_fields=["name"])

            for idx, status_data in enumerate(statuses_data):
                if not isinstance(status_data, dict):
                    continue
                status_id = status_data.get("id")
                status_name = str(status_data.get("name", "")).strip() or f"Status {idx + 1}"
                is_terminal = bool(status_data.get("is_terminal", False))
                status_color = normalize_color(
                    status_data.get("color"),
                    DEFAULT_STAGE_COLORS[idx % len(DEFAULT_STAGE_COLORS)],
                )

                status_obj = None
                try:
                    parsed_id = int(status_id)
                except (TypeError, ValueError):
                    parsed_id = None

                if parsed_id and parsed_id in existing_status_ids:
                    status_obj = existing_status_map.get(parsed_id)

                if status_obj is None:
                    try:
                        status_obj = workflow.statuses.create(
                            name=status_name,
                            order=idx,
                            is_terminal=is_terminal,
                            color=status_color,
                        )
                    except IntegrityError:
                        return Response(
                            {"detail": f"Status name '{status_name}' already exists in this workflow."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    dirty = True
                else:
                    if (
                        status_obj.name != status_name
                        or status_obj.order != idx
                        or status_obj.is_terminal != is_terminal
                        or status_obj.color != status_color
                    ):
                        status_obj.name = status_name
                        status_obj.order = idx
                        status_obj.is_terminal = is_terminal
                        status_obj.color = status_color
                        try:
                            status_obj.save(update_fields=["name", "order", "is_terminal", "color"])
                        except IntegrityError:
                            return Response(
                                {"detail": f"Status name '{status_name}' already exists in this workflow."},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        dirty = True

                seen_status_ids.add(status_obj.id)

            statuses_to_delete = existing_status_ids - seen_status_ids
            if statuses_to_delete:
                workflow.statuses.filter(id__in=statuses_to_delete).delete()
                dirty = True

        transition_rules_data = request.data.get("transition_rules")
        if isinstance(transition_rules_data, list):
            current_status_ids = set(workflow.statuses.values_list("id", flat=True))
            workflow.transition_rules.all().delete()
            dirty = True

            for rule_data in transition_rules_data:
                if not isinstance(rule_data, dict):
                    continue

                from_status = None
                to_status = None

                try:
                    from_status_id = int(rule_data.get("from_status"))
                    if from_status_id in current_status_ids:
                        from_status = workflow.statuses.filter(id=from_status_id).first()
                except (TypeError, ValueError):
                    from_status = None
                try:
                    to_status_id = int(rule_data.get("to_status"))
                    if to_status_id in current_status_ids:
                        to_status = workflow.statuses.filter(id=to_status_id).first()
                except (TypeError, ValueError):
                    to_status = None

                if from_status is None:
                    from_name = str(rule_data.get("from_status_name", "")).strip()
                    if from_name:
                        from_status = workflow.statuses.filter(name__iexact=from_name).first()
                if to_status is None:
                    to_name = str(rule_data.get("to_status_name", "")).strip()
                    if to_name:
                        to_status = workflow.statuses.filter(name__iexact=to_name).first()

                if from_status is None or to_status is None:
                    continue

                allowed_roles_raw = rule_data.get("allowed_roles") or []
                allowed_roles = []
                if isinstance(allowed_roles_raw, list):
                    for role in allowed_roles_raw:
                        normalized = str(role).strip().upper().replace(" ", "_")
                        if normalized:
                            allowed_roles.append(normalized)

                rule = TransitionRule.objects.create(
                    workflow=workflow,
                    from_status=from_status,
                    to_status=to_status,
                    allowed_roles=allowed_roles,
                )

                requirements = rule_data.get("proof_requirements") or []
                if isinstance(requirements, list):
                    for req in requirements:
                        if not isinstance(req, dict):
                            continue
                        req_type = str(req.get("type", "")).strip().upper()
                        if req_type not in {ProofRequirement.Type.FILE, ProofRequirement.Type.TEXT, ProofRequirement.Type.URL}:
                            continue
                        label = str(req.get("label", "")).strip() or f"{req_type} proof"
                        ProofRequirement.objects.create(
                            transition_rule=rule,
                            type=req_type,
                            label=label,
                            is_mandatory=bool(req.get("is_mandatory", True)),
                        )

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
        if not Workflow.objects.filter(
            tenant=workflow.tenant,
            is_default=True,
        ).exclude(id=workflow.id).exists():
            workflow.is_default = True
        workflow.version = F("version") + 1
        workflow.save(update_fields=["is_published", "published_at", "is_default", "version"])
        workflow.refresh_from_db(fields=["version", "is_published", "published_at", "is_default"])

        serializer = self.get_serializer(workflow)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="set-default",
        permission_classes=[IsAuthenticated, IsAdminRole],
    )
    @transaction.atomic
    def set_default(self, request, pk=None):
        workflow = self.get_object()
        Workflow.objects.filter(
            tenant=workflow.tenant,
            is_default=True,
        ).exclude(id=workflow.id).update(is_default=False)
        if not workflow.is_default:
            workflow.is_default = True
            workflow.save(update_fields=["is_default"])

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
                    color=DEFAULT_STAGE_COLORS[idx % len(DEFAULT_STAGE_COLORS)],
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

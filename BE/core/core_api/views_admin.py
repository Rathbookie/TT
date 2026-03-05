from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from rest_framework import status

from users.models import User, UserRole, Role
from core_api.models import Task, TaskHistory
from core_api.permissions import IsAdminRole
from workflows.models import TenantModule, DashboardConfig


def _status_name(task):
    return task.status.name if task.status else "Unassigned"


class AdminDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        # JWT auth guarantees request.user; tenant hangs off user model.
        tenant = request.user.tenant

        tasks = Task.objects.filter(tenant=tenant, is_deleted=False)
        users = User.objects.filter(tenant=tenant)

        total_users = users.count()
        active_tasks = tasks.filter(status__name__iexact="In Progress").count()
        blocked_tasks = tasks.filter(status__name__iexact="Blocked").count()
        done_tasks = tasks.filter(status__is_terminal=True, status__is_cancelled=False).count()

        total_tasks = tasks.count()
        completion_rate = (
            round((done_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        # Status Overview
        status_counts = (
            tasks.values("status__name")
            .annotate(count=Count("id"))
        )

        status_overview = [
            {
                "name": item["status__name"] or "Unassigned",
                "count": item["count"],
            }
            for item in status_counts
        ]

        # Recent Activity
        recent_history = (
            TaskHistory.objects
            .filter(task__tenant=tenant)
            .order_by("-timestamp")[:10]
        )

        recent_activity = [
            {
                "id": h.id,
                "message": f"{h.action} on '{h.task.title}'"
            }
            for h in recent_history
        ]

        user_ids = list(users.values_list("id", flat=True))
        roles_by_user = {}
        for user_id, role_name in UserRole.objects.filter(
            tenant=tenant,
            user_id__in=user_ids,
        ).values_list("user_id", "role__name"):
            roles_by_user.setdefault(user_id, []).append(role_name)

        # Users list (basic)
        users_data = []
        for u in users:
            roles = roles_by_user.get(u.id, [])
            users_data.append({
                "id": u.id,
                "email": u.email,
                # Keep singular field for compatibility with old clients.
                "role": roles[0] if roles else None,
                "roles": roles,
                "is_active": u.is_active,
            })

        return Response({
            "kpis": {
                "total_users": total_users,
                "active_tasks": active_tasks,
                "blocked_tasks": blocked_tasks,
                "completion_rate": completion_rate,
            },
            "status_overview": status_overview,
            "recent_activity": recent_activity,
            "users": users_data,
        })


class DashboardWidgetsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = request.user.tenant
        tasks = Task.objects.filter(tenant=tenant, is_deleted=False)

        now = timezone.now()
        overdue_count = tasks.filter(
            due_date__isnull=False,
            due_date__lt=now,
        ).exclude(status__is_terminal=True, status__is_cancelled=False).count()
        active_count = tasks.filter(status__name__iexact="In Progress").count()
        done_count = tasks.filter(status__is_terminal=True, status__is_cancelled=False).count()
        total_count = tasks.count()
        completion_rate = round((done_count / total_count) * 100, 1) if total_count else 0

        stage_distribution = list(
            tasks.values("status__name").annotate(count=Count("id")).order_by("status__name")
        )

        recent_activity = [
            {
                "id": h.id,
                "message": f"{h.action} on '{h.task.title}'",
                "timestamp": h.timestamp,
            }
            for h in TaskHistory.objects.filter(task__tenant=tenant).order_by("-timestamp")[:10]
        ]

        my_tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": _status_name(t),
                "priority": t.priority,
                "due_date": t.due_date,
            }
            for t in tasks.filter(assignees=request.user).distinct().order_by("due_date")[:10]
        ]

        approval_queue = [
            {
                "id": t.id,
                "title": t.title,
                "status": _status_name(t),
            }
            for t in tasks.filter(status__name__iexact="In Review").order_by("-updated_at")[:10]
        ]

        enabled_module_keys = set(
            TenantModule.objects.filter(
                tenant=tenant,
                is_enabled=True,
            ).values_list("module__key", flat=True)
        )

        widget_payload = [
            {
                "key": "tasks_overdue",
                "title": "Tasks Overdue",
                "value": overdue_count,
            },
            {
                "key": "active_tasks",
                "title": "Active Tasks",
                "value": active_count,
            },
            {
                "key": "completion_rate",
                "title": "Completion Rate",
                "value": completion_rate,
            },
            {
                "key": "workflow_stage_distribution",
                "title": "Workflow Stage Distribution",
                "data": stage_distribution,
            },
            {
                "key": "my_tasks",
                "title": "My Tasks",
                "data": my_tasks,
            },
            {
                "key": "recent_activity",
                "title": "Recent Activity",
                "data": recent_activity,
            },
        ]

        if "approvals" in enabled_module_keys:
            widget_payload.append(
                {
                    "key": "approval_queue",
                    "title": "Approval Queue",
                    "data": approval_queue,
                }
            )

        return Response(
            {
                "widgets": widget_payload,
                "modules_enabled": list(enabled_module_keys),
            }
        )


class DashboardConfigView(APIView):
    permission_classes = [IsAuthenticated]

    DEFAULT_WIDGETS = [
        {"id": "w-featured", "key": "featured", "size": "l", "settings": {"prompt": "", "output": ""}},
        {"id": "w-task-table", "key": "task_table", "size": "l", "settings": {"mode": "all", "limit": 12}},
        {"id": "w-workload", "key": "workload_by_status", "size": "m", "settings": {}},
        {"id": "w-due-soon", "key": "tasks_due_soon", "size": "m", "settings": {}},
        {"id": "w-recent-activity", "key": "recent_activity", "size": "m", "settings": {}},
        {"id": "w-overdue", "key": "overdue_tasks", "size": "m", "settings": {}},
    ]

    def _is_admin(self, user):
        return user.user_roles.filter(
            tenant=user.tenant,
            role__name__iexact=Role.ADMIN,
        ).exists()

    def _parse_scope_key(self, request):
        scope_key = request.query_params.get("scope_key") or request.data.get("scope_key")
        if scope_key is None:
            return None
        scope_key = str(scope_key).strip()
        return scope_key or None

    def _scope_dashboard_name(self, scope_key):
        return f"__scope__{scope_key}"

    def _can_view(self, dashboard, user, is_admin):
        if is_admin:
            return True
        if dashboard.visibility == DashboardConfig.Visibility.PRIVATE:
            return dashboard.owner_id == user.id
        return True

    def _can_edit(self, dashboard, user, is_admin):
        if is_admin:
            return True
        # Private dashboards remain owner-edit only.
        if dashboard.visibility == DashboardConfig.Visibility.PRIVATE:
            return dashboard.owner_id == user.id
        # Internal/Public dashboards are editable by tenant members.
        return True

    def _get_or_create_default(self, user):
        dashboard = DashboardConfig.objects.filter(
            tenant=user.tenant,
            is_default=True,
        ).first()
        if dashboard:
            return dashboard
        return DashboardConfig.objects.create(
            tenant=user.tenant,
            owner=user,
            name="Dashboard",
            visibility=DashboardConfig.Visibility.INTERNAL,
            is_default=True,
            global_filters={},
            widgets=self.DEFAULT_WIDGETS,
            auto_refresh_seconds=30,
        )

    def _get_or_create_scoped(self, user, scope_key):
        name = self._scope_dashboard_name(scope_key)
        dashboard = DashboardConfig.objects.filter(
            tenant=user.tenant,
            name=name,
        ).first()
        if dashboard:
            return dashboard
        return DashboardConfig.objects.create(
            tenant=user.tenant,
            owner=user,
            name=name,
            visibility=DashboardConfig.Visibility.INTERNAL,
            is_default=False,
            global_filters={},
            widgets=self.DEFAULT_WIDGETS,
            auto_refresh_seconds=30,
        )

    def _serialize_dashboard(self, dashboard, user, is_admin):
        scope_key = None
        if dashboard.name.startswith("__scope__"):
            scope_key = dashboard.name.replace("__scope__", "", 1)
        return {
            "id": dashboard.id,
            "name": dashboard.name,
            "scope_key": scope_key,
            "visibility": dashboard.visibility,
            "is_default": dashboard.is_default,
            "global_filters": dashboard.global_filters or {},
            "widgets": dashboard.widgets or [],
            "auto_refresh_seconds": dashboard.auto_refresh_seconds,
            "owner_id": dashboard.owner_id,
            "can_edit": self._can_edit(dashboard, user, is_admin),
            "updated_at": dashboard.updated_at,
        }

    def get(self, request):
        user = request.user
        is_admin = self._is_admin(user)
        scope_key = self._parse_scope_key(request)

        if scope_key:
            scoped_dashboard = self._get_or_create_scoped(user, scope_key)
            return Response(
                {
                    "dashboard": self._serialize_dashboard(scoped_dashboard, user, is_admin),
                    "dashboards": [
                        {
                            "id": scoped_dashboard.id,
                            "name": scoped_dashboard.name,
                            "visibility": scoped_dashboard.visibility,
                            "is_default": scoped_dashboard.is_default,
                            "can_edit": self._can_edit(scoped_dashboard, user, is_admin),
                            "scope_key": scope_key,
                        }
                    ],
                }
            )

        self._get_or_create_default(user)

        dashboards = list(
            DashboardConfig.objects.filter(tenant=user.tenant).order_by("name", "-updated_at")
        )
        visible = [d for d in dashboards if self._can_view(d, user, is_admin)]
        if not visible:
            return Response({"detail": "No accessible dashboard found."}, status=status.HTTP_404_NOT_FOUND)

        requested_id = request.query_params.get("dashboard_id")
        selected = None
        if requested_id:
            try:
                parsed = int(requested_id)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                selected = next((d for d in visible if d.id == parsed), None)
        if selected is None:
            selected = next((d for d in visible if d.is_default), None) or visible[0]

        return Response(
            {
                "dashboard": self._serialize_dashboard(selected, user, is_admin),
                "dashboards": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "visibility": d.visibility,
                        "is_default": d.is_default,
                        "can_edit": self._can_edit(d, user, is_admin),
                    }
                    for d in visible
                ],
            }
        )

    def post(self, request):
        user = request.user
        if not self._is_admin(user):
            return Response(
                {"detail": "Only admin can create dashboards."},
                status=status.HTTP_403_FORBIDDEN,
            )
        scope_key = self._parse_scope_key(request)
        if scope_key:
            dashboard = self._get_or_create_scoped(user, scope_key)
            if "widgets" in request.data and isinstance(request.data.get("widgets"), list):
                dashboard.widgets = request.data.get("widgets")
            if "global_filters" in request.data and isinstance(request.data.get("global_filters"), dict):
                dashboard.global_filters = request.data.get("global_filters")
            if "auto_refresh_seconds" in request.data:
                try:
                    seconds = int(request.data.get("auto_refresh_seconds"))
                except (TypeError, ValueError):
                    seconds = 30
                dashboard.auto_refresh_seconds = max(10, min(seconds, 3600))
            dashboard.save()
            return Response(
                self._serialize_dashboard(dashboard, user, True),
                status=status.HTTP_201_CREATED,
            )
        name = str(request.data.get("name", "")).strip() or "Dashboard"
        base_name = name
        idx = 2
        while DashboardConfig.objects.filter(tenant=user.tenant, name=name).exists():
            name = f"{base_name} {idx}"
            idx += 1
        dashboard = DashboardConfig.objects.create(
            tenant=user.tenant,
            owner=user,
            name=name,
            visibility=str(request.data.get("visibility", DashboardConfig.Visibility.INTERNAL)).upper(),
            is_default=False,
            global_filters={},
            widgets=request.data.get("widgets") or self.DEFAULT_WIDGETS,
            auto_refresh_seconds=30,
        )
        return Response(
            self._serialize_dashboard(dashboard, user, True),
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request):
        user = request.user
        is_admin = self._is_admin(user)
        scope_key = self._parse_scope_key(request)

        if scope_key:
            dashboard = self._get_or_create_scoped(user, scope_key)
            if not self._can_edit(dashboard, user, is_admin):
                return Response({"detail": "You cannot edit this dashboard."}, status=status.HTTP_403_FORBIDDEN)
            if "auto_refresh_seconds" in request.data:
                try:
                    seconds = int(request.data.get("auto_refresh_seconds"))
                except (TypeError, ValueError):
                    return Response({"detail": "auto_refresh_seconds must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
                dashboard.auto_refresh_seconds = max(10, min(seconds, 3600))
            if "global_filters" in request.data:
                filters = request.data.get("global_filters")
                if not isinstance(filters, dict):
                    return Response({"detail": "global_filters must be an object."}, status=status.HTTP_400_BAD_REQUEST)
                dashboard.global_filters = filters
            if "widgets" in request.data:
                widgets = request.data.get("widgets")
                if not isinstance(widgets, list):
                    return Response({"detail": "widgets must be a list."}, status=status.HTTP_400_BAD_REQUEST)
                dashboard.widgets = widgets
            dashboard.save()
            return Response(self._serialize_dashboard(dashboard, user, is_admin))

        dashboard_id = request.data.get("dashboard_id") or request.query_params.get("dashboard_id")
        if not dashboard_id:
            return Response({"detail": "dashboard_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            dashboard_id = int(dashboard_id)
        except (TypeError, ValueError):
            return Response({"detail": "dashboard_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        dashboard = DashboardConfig.objects.filter(
            tenant=user.tenant,
            id=dashboard_id,
        ).first()
        if not dashboard:
            return Response({"detail": "Dashboard not found."}, status=status.HTTP_404_NOT_FOUND)

        if not self._can_edit(dashboard, user, is_admin):
            return Response({"detail": "You cannot edit this dashboard."}, status=status.HTTP_403_FORBIDDEN)

        if "name" in request.data:
            name = str(request.data.get("name", "")).strip()
            if name:
                dashboard.name = name
        if "visibility" in request.data:
            visibility = str(request.data.get("visibility", "")).upper()
            allowed = {choice[0] for choice in DashboardConfig.Visibility.choices}
            if visibility not in allowed:
                return Response({"detail": "Invalid visibility."}, status=status.HTTP_400_BAD_REQUEST)
            dashboard.visibility = visibility
        if "auto_refresh_seconds" in request.data:
            try:
                seconds = int(request.data.get("auto_refresh_seconds"))
            except (TypeError, ValueError):
                return Response({"detail": "auto_refresh_seconds must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
            dashboard.auto_refresh_seconds = max(10, min(seconds, 3600))
        if "global_filters" in request.data:
            filters = request.data.get("global_filters")
            if not isinstance(filters, dict):
                return Response({"detail": "global_filters must be an object."}, status=status.HTTP_400_BAD_REQUEST)
            dashboard.global_filters = filters
        if "widgets" in request.data:
            widgets = request.data.get("widgets")
            if not isinstance(widgets, list):
                return Response({"detail": "widgets must be a list."}, status=status.HTTP_400_BAD_REQUEST)
            dashboard.widgets = widgets

        dashboard.save()
        return Response(self._serialize_dashboard(dashboard, user, is_admin))

    def delete(self, request):
        user = request.user
        is_admin = self._is_admin(user)
        dashboard_id = request.query_params.get("dashboard_id")
        if not dashboard_id:
            return Response({"detail": "dashboard_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            dashboard_id = int(dashboard_id)
        except (TypeError, ValueError):
            return Response({"detail": "dashboard_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        dashboard = DashboardConfig.objects.filter(
            tenant=user.tenant,
            id=dashboard_id,
        ).first()
        if not dashboard:
            return Response({"detail": "Dashboard not found."}, status=status.HTTP_404_NOT_FOUND)
        if dashboard.is_default:
            return Response({"detail": "Default dashboard cannot be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        if not self._can_edit(dashboard, user, is_admin):
            return Response({"detail": "You cannot delete this dashboard."}, status=status.HTTP_403_FORBIDDEN)
        dashboard.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

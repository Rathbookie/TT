from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from users.models import User, UserRole
from core_api.models import Task, TaskHistory
from core_api.permissions import IsAdminRole


class AdminDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        # JWT auth guarantees request.user; tenant hangs off user model.
        tenant = request.user.tenant

        tasks = Task.objects.filter(tenant=tenant, is_deleted=False)
        users = User.objects.filter(tenant=tenant)

        total_users = users.count()
        active_tasks = tasks.filter(status="IN_PROGRESS").count()
        blocked_tasks = tasks.filter(status="BLOCKED").count()
        done_tasks = tasks.filter(status="DONE").count()

        total_tasks = tasks.count()
        completion_rate = (
            round((done_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        # Status Overview
        status_counts = (
            tasks.values("status")
            .annotate(count=Count("id"))
        )

        status_map = {
            "NOT_STARTED": "Not Started",
            "IN_PROGRESS": "In Progress",
            "BLOCKED": "Blocked",
            "WAITING": "Waiting",
            "DONE": "Done",
            "CANCELLED": "Cancelled",
        }

        status_overview = [
            {
                "name": status_map.get(item["status"], item["status"]),
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

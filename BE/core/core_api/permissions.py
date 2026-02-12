from rest_framework.permissions import BasePermission
from users.models import Role
from users.utils import is_admin, user_has_role


class TaskPermission(BasePermission):

    def has_permission(self, request, view):
        if is_admin(request.user):
            return True

        if view.action == "create":
            return user_has_role(request.user, Role.TASK_CREATOR)

        return True

    def has_object_permission(self, request, view, obj):
        if is_admin(request.user):
            return True

        if obj.created_by_id == request.user.id:
            return True

        if obj.assigned_to_id == request.user.id:
            return True

        return False

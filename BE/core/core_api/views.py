from django.db.models import Q
from django.utils import timezone

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied

from core_api.models import Task
from core_api.serializers import TaskSerializer
from core_api.permissions import TaskPermission
from users.utils import is_admin


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


class TaskViewSet(ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, TaskPermission]

    def get_queryset(self):
        user = self.request.user

        if not user or not user.is_authenticated:
            return Task.objects.none()

        tenant = user.tenant

        queryset = Task.objects.for_tenant(tenant).filter(is_deleted=False)

        if is_admin(user):
            return queryset

        return queryset.filter(
            Q(created_by=user) | Q(assigned_to=user)
        )

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        instance = self.get_object()

        if instance.tenant != self.request.user.tenant:
            raise PermissionDenied("Cross-tenant modification forbidden.")

        if instance.is_deleted:
            raise PermissionDenied("Cannot modify deleted task.")

        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        if instance.tenant != self.request.user.tenant:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        if instance.is_deleted:
            return  # already deleted

        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save()

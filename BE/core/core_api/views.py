from django.db.models import Q
from django.utils import timezone

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action

from core_api.serializers import TaskSerializer
from core_api.permissions import TaskPermission
from core_api.models import Task, TaskHistory
from core_api.serializers import TaskHistorySerializer

from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.exceptions import ValidationError


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

        return Task.objects.for_tenant(tenant).filter(
            is_deleted=False
        ).filter(
            Q(created_by=user) | Q(assigned_to=user)
        )

    def perform_create(self, serializer):
        task = serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user,
        )

        TaskHistory.objects.create(
            tenant=task.tenant,
            task=task,
            action=TaskHistory.Action.CREATED,
            performed_by=self.request.user,
            title=task.title,
            description=task.description,
            status=task.status,
        )

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            instance = self.get_object()

            if instance.tenant != request.user.tenant:
                raise PermissionDenied("Cross-tenant modification forbidden.")

            if instance.is_deleted:
                raise PermissionDenied("Cannot modify deleted task.")

            client_version = request.data.get("version")

            if client_version is None:
                raise ValidationError({"version": "Version is required."})

            if int(client_version) != instance.version:
                return Response(
                    {"detail": "Conflict detected. Task was modified by another user."},
                    status=status.HTTP_409_CONFLICT,
                )

            serializer = self.get_serializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)

            task = serializer.save(
                updated_by=request.user,
                version=F("version") + 1,
            )

            task.refresh_from_db()

            TaskHistory.objects.create(
                tenant=task.tenant,
                task=task,
                action=TaskHistory.Action.UPDATED,
                performed_by=request.user,
                title=task.title,
                description=task.description,
                status=task.status,
            )

            return Response(self.get_serializer(task).data)


    def perform_destroy(self, instance):
        if instance.tenant != self.request.user.tenant:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        if instance.is_deleted:
            return  # already deleted

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
            status=instance.status,
    
    )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        task = self.get_object()

        # Tenant safety
        if task.tenant != request.user.tenant:
            raise PermissionDenied("Cross-tenant access forbidden.")

        queryset = TaskHistory.objects.filter(
            task=task,
            tenant=request.user.tenant
        ).order_by("-timestamp")

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TaskHistorySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = TaskHistorySerializer(queryset, many=True)
        return Response(serializer.data)
    

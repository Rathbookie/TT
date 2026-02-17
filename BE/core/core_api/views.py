from django.db.models import Q
from django.utils import timezone

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser


from core_api.serializers import TaskSerializer
from core_api.permissions import TaskPermission
from core_api.models import Task, TaskHistory
from core_api.serializers import TaskHistorySerializer

from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.exceptions import ValidationError

from rest_framework.parsers import MultiPartParser, FormParser
from .models import TaskAttachment
from .serializers import TaskAttachmentSerializer

from users.models import UserRole

from core_api.pagination import TaskPagination


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    tenant = user.tenant

    roles = list(
        UserRole.objects.filter(user=user, tenant=tenant)
        .values_list("role__name", flat=True)
    )

    return Response({
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": roles,
    })


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
            is_deleted=False
        )

        active_role = self.request.headers.get("X-Active-Role")

        # Fetch roles assigned to this user in this tenant
        user_roles = list(
            UserRole.objects.filter(user=user, tenant=tenant)
            .values_list("role__name", flat=True)
        )

        # If client sends invalid role → deny access
        if active_role not in user_roles:
            return qs.none()

        if active_role == "TASK_RECEIVER":
            qs = qs.filter(assigned_to=user)

        elif active_role == "TASK_CREATOR":
            qs = qs.filter(created_by=user)

        elif active_role == "ADMIN":
            pass  # Full tenant access

        return qs
    

    def perform_create(self, serializer):
        user = self.request.user
        tenant = user.tenant

        active_role = self.request.headers.get("X-Active-Role")

        user_roles = list(
            UserRole.objects.filter(user=user, tenant=tenant)
            .values_list("role__name", flat=True)
        )

        # Validate active role exists and belongs to user
        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        # Only TASK_CREATOR or ADMIN can create tasks
        if active_role not in ["TASK_CREATOR", "ADMIN"]:
            raise PermissionDenied("You do not have permission to create tasks.")

        task = serializer.save(
            tenant=tenant,
            created_by=user,
        )

        TaskHistory.objects.create(
            tenant=task.tenant,
            task=task,
            action=TaskHistory.Action.CREATED,
            performed_by=user,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
    )


    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            instance = self.get_object()

            if instance.tenant != request.user.tenant:
                raise PermissionDenied("Cross-tenant modification forbidden.")
            
            active_role = request.headers.get("X-Active-Role")

            user_roles = list(
                UserRole.objects.filter(user=request.user, tenant=request.user.tenant)
                .values_list("role__name", flat=True)
            )

            if active_role not in user_roles:
                raise PermissionDenied("Invalid active role.")

            # Permission logic
            if active_role == "TASK_RECEIVER":
                raise PermissionDenied("Task receivers cannot modify tasks.")

            if active_role == "TASK_CREATOR" and instance.created_by != request.user:
                raise PermissionDenied("You can only modify tasks you created.")

            if instance.is_deleted:
                raise PermissionDenied("Cannot modify deleted task.")

            if instance.status == Task.Status.DONE:
                raise PermissionDenied("Completed tasks cannot be modified.")

            client_version = request.data.get("version")

            if client_version is None:
                raise ValidationError({"version": "Version is required."})

            if int(client_version) != instance.version:
                return Response(
                    {"detail": "Conflict detected. Task was modified by another user."},
                    status=status.HTTP_409_CONFLICT,
                )

            serializer = self.get_serializer(instance, 
                                             data=request.data,
                                             partial=True
            )
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
                priority=task.priority,
                due_date=task.due_date,
            )

            return Response(self.get_serializer(task).data)


    def perform_destroy(self, instance):

        active_role = self.request.headers.get("X-Active-Role")
        user_roles = list(
            UserRole.objects.filter(user=self.request.user, tenant=self.request.user.tenant)
            .values_list("role__name", flat=True)
        )

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        if active_role == "TASK_RECEIVER":
            raise PermissionDenied("Task receivers cannot delete tasks.")

        if active_role == "TASK_CREATOR" and instance.created_by != self.request.user:
            raise PermissionDenied("You can only delete tasks you created.")
        
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
            priority=instance.priority,
            due_date=instance.due_date,
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
    
    @action(
    detail=True,
    methods=["post"],
    url_path="attachments",
    parser_classes=[MultiPartParser, FormParser],
    )
    def upload_attachment(self, request, pk=None):
        task = self.get_object()

        if task.tenant != request.user.tenant:
            raise PermissionDenied("Cross-tenant upload forbidden.")

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
        )

        serializer = TaskAttachmentSerializer(attachment,context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(
    detail=True,
    methods=["delete"],
    url_path="attachments/(?P<attachment_id>[^/.]+)"
    )
    def delete_attachment(self, request, pk=None, attachment_id=None):
        task = self.get_object()

        if task.tenant != request.user.tenant:
            raise PermissionDenied("Cross-tenant deletion forbidden.")

        try:
            attachment = TaskAttachment.objects.get(
                id=attachment_id,
                task=task,
                tenant=request.user.tenant,
            )
        except TaskAttachment.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
        

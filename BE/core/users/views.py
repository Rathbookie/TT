from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

from users.throttling import LoginRateThrottle
from .token_serializer import CustomTokenObtainPairSerializer
from .models import User, Role, UserRole

from core_api.serializers import TaskUserSerializer
from users.utils import is_admin

UserModel = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]


def _safe_username_from_email(email: str) -> str:
    base = (email.split("@")[0] or "user").strip().lower().replace(" ", ".")
    if not base:
        base = "user"
    username = base
    counter = 1
    while UserModel.objects.filter(username__iexact=username).exists():
        counter += 1
        username = f"{base}{counter}"
    return username


class TenantUserListView(generics.ListCreateAPIView):
    serializer_class = TaskUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        tenant = user.tenant
        # Read-only org directory: any authenticated user in the tenant can list/search users.
        queryset = User.objects.filter(tenant=tenant)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        return queryset.order_by("first_name", "last_name", "email")

    def create(self, request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Only admins can create users.")

        first_name = str(request.data.get("first_name", "")).strip()
        last_name = str(request.data.get("last_name", "")).strip()
        email = str(request.data.get("email", "")).strip().lower()
        password = str(request.data.get("password", "")).strip()
        role_name = str(request.data.get("role", Role.TASK_RECEIVER)).strip().upper()

        if not first_name or not last_name or not email or not password:
            raise ValidationError("first_name, last_name, email, and password are required.")

        if role_name not in {Role.ADMIN, Role.TASK_CREATOR, Role.TASK_RECEIVER}:
            raise ValidationError("Invalid role.")

        try:
            validate_email(email)
        except DjangoValidationError:
            raise ValidationError("Enter a valid email address.")

        if UserModel.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email is already in use.")

        temp_user = UserModel(
            username=_safe_username_from_email(email),
            email=email,
            first_name=first_name,
            last_name=last_name,
            tenant=request.user.tenant,
        )
        try:
            validate_password(password, user=temp_user)
        except Exception as exc:
            message = str(exc)
            if hasattr(exc, "messages") and getattr(exc, "messages"):
                message = str(exc.messages[0])
            raise ValidationError(message)

        temp_user.set_password(password)
        temp_user.save()

        role_obj, _ = Role.objects.get_or_create(name=role_name)
        UserRole.objects.get_or_create(
            user=temp_user,
            tenant=request.user.tenant,
            role=role_obj,
        )

        return Response(
            TaskUserSerializer(temp_user).data,
            status=status.HTTP_201_CREATED,
        )


class TenantUserDetailView(generics.DestroyAPIView):
    serializer_class = TaskUserSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "user_id"

    def get_queryset(self):
        return User.objects.filter(tenant=self.request.user.tenant)

    def destroy(self, request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Only admins can remove users.")
        instance = self.get_object()
        if instance.id == request.user.id:
            raise ValidationError("You cannot remove your own account.")
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

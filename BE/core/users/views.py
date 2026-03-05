from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q

from users.throttling import LoginRateThrottle
from .token_serializer import CustomTokenObtainPairSerializer
from .models import User, UserRole

from core_api.serializers import TaskUserSerializer

def normalize_role_value(value):
    if value is None:
        return None
    return str(value).strip().upper().replace(" ", "_")


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]


class TenantUserListView(generics.ListAPIView):
    serializer_class = TaskUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        tenant = user.tenant

        active_role = normalize_role_value(self.request.headers.get("X-Active-Role"))

        user_roles = {
            normalized
            for normalized in (
                normalize_role_value(role)
                for role in UserRole.objects.filter(user=user, tenant=tenant).values_list(
                    "role__name", flat=True
                )
            )
            if normalized
        }

        if active_role and active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        # Search endpoint is read-only; allow all task roles in the tenant.
        if not user_roles.intersection({"TASK_CREATOR", "TASK_RECEIVER", "ADMIN"}):
            raise PermissionDenied("You do not have permission to view users.")

        queryset = User.objects.filter(tenant=tenant)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        return queryset.order_by("first_name", "last_name", "email")

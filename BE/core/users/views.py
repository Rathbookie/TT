from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied

from users.throttling import LoginRateThrottle
from .token_serializer import CustomTokenObtainPairSerializer
from .models import User, UserRole

from core_api.serializers import TaskUserSerializer


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

        active_role = self.request.headers.get("X-Active-Role")

        user_roles = list(
            UserRole.objects.filter(user=user, tenant=tenant)
            .values_list("role__name", flat=True)
        )

        if active_role not in user_roles:
            raise PermissionDenied("Invalid active role.")

        if active_role not in ["TASK_CREATOR", "ADMIN"]:
            raise PermissionDenied("You do not have permission to view users.")

        return User.objects.filter(tenant=tenant)

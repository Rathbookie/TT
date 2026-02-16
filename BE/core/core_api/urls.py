from django.urls import path
from rest_framework.routers import DefaultRouter

from users.views import CustomTokenObtainPairView, TenantUserListView
from .views import health, TaskViewSet, me

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")

urlpatterns = [
    path("health/", health),
    path("me/", me, name="me"),

    # JWT login endpoint
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),

    # Tenant users endpoint
    path("users/", TenantUserListView.as_view(), name="tenant-users"),
]

urlpatterns += router.urls

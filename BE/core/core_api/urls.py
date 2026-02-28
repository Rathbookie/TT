from django.urls import path
from rest_framework.routers import DefaultRouter

from users.views import CustomTokenObtainPairView, TenantUserListView
from .views import health, TaskViewSet, me
from .views_admin import AdminDashboardView, DashboardWidgetsView, DashboardConfigView
from workflows.views import WorkflowViewSet, WorkflowPresetViewSet, TenantModuleViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")
router.register("workflows", WorkflowViewSet, basename="workflows")
router.register("workflow-presets", WorkflowPresetViewSet, basename="workflow-presets")
router.register("modules", TenantModuleViewSet, basename="modules")

urlpatterns = [
    path("health/", health),
    path("me/", me, name="me"),

    # JWT login endpoint
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),

    # Tenant users endpoint
    path("users/", TenantUserListView.as_view(), name="tenant-users"),

    # Admin dashboard endpoint
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("dashboard/widgets/", DashboardWidgetsView.as_view(), name="dashboard-widgets"),
    path("dashboard/config/", DashboardConfigView.as_view(), name="dashboard-config"),
]

urlpatterns += router.urls

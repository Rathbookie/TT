from django.urls import path
from rest_framework.routers import DefaultRouter

from users.views import CustomTokenObtainPairView, TenantUserListView
from .views import (
    health,
    TaskViewSet,
    me,
    DivisionViewSet,
    SectionViewSet,
    BoardViewSet,
    TaskStatusViewSet,
    org_divisions,
    org_division_detail,
    org_division_sections,
    org_division_members,
    org_division_boards,
    org_section_boards,
    org_task_by_ref,
    org_subtask_by_ref,
)
from .views_admin import AdminDashboardView, DashboardWidgetsView, DashboardConfigView
from workflows.views import WorkflowViewSet, WorkflowPresetViewSet, TenantModuleViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")
router.register("divisions", DivisionViewSet, basename="divisions")
router.register("sections", SectionViewSet, basename="sections")
router.register("boards", BoardViewSet, basename="boards")
router.register("task-statuses", TaskStatusViewSet, basename="task-statuses")
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

    # Slug-based hierarchy/task routes
    path("<slug:org_slug>/divisions/", org_divisions, name="org-divisions"),
    path("<slug:org_slug>/divisions/<slug:division_slug>/", org_division_detail, name="org-division-detail"),
    path("<slug:org_slug>/divisions/<slug:division_slug>/sections/", org_division_sections, name="org-division-sections"),
    path("<slug:org_slug>/divisions/<slug:division_slug>/members/", org_division_members, name="org-division-members"),
    path("<slug:org_slug>/divisions/<slug:division_slug>/boards/", org_division_boards, name="org-division-boards"),
    path("<slug:org_slug>/divisions/<slug:division_slug>/<slug:section_slug>/boards/", org_section_boards, name="org-section-boards"),
    path("<slug:org_slug>/task/<str:task_ref>/", org_task_by_ref, name="org-task-by-ref"),
    path("<slug:org_slug>/task/<str:task_ref>/sub/<str:sub_ref>/", org_subtask_by_ref, name="org-subtask-by-ref"),
]

urlpatterns += router.urls

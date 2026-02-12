from django.urls import path
from .views import MeView, PermissionsView, WorkspaceView

urlpatterns = [
    path("me/", MeView.as_view(), name="context-me"),
    path("permissions/", PermissionsView.as_view(), name="context-permissions"),
    path("workspace/", WorkspaceView.as_view(), name="context-workspace"),
]

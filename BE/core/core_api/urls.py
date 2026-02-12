from django.urls import path
from rest_framework.routers import DefaultRouter
from users.views import CustomTokenObtainPairView

from .views import health, TaskViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")

urlpatterns = [
    path("health/", health),

    # JWT login endpoint
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
]

urlpatterns += router.urls

from django.contrib import admin
from django.urls import path, include
from users.views import CustomTokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # JWT
    path("api/token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # App routes
    path("api/", include("core_api.urls")),
    path("context/", include("context.urls")),
]

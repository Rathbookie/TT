from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from users.throttling import LoginRateThrottle
from .token_serializer import CustomTokenObtainPairSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

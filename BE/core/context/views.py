from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .serializers import MeSerializer, PermissionsSerializer
from .permissions import ROLE_PERMISSIONS


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        data = {
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "role": u.role,
            "created_at": u.date_joined,
        }
        return Response(MeSerializer(data).data)


class PermissionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.user.role
        permissions = ROLE_PERMISSIONS.get(role, [])

        data = {
            "role": role,
            "permissions": permissions,
        }
        return Response(PermissionsSerializer(data).data)

class WorkspaceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = {
            "workspace": {
                "id": "default",
                "name": "Task Tracker",
                "role": request.user.role,
            }
        }
        return Response(data)
        

from rest_framework import serializers

class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role = serializers.CharField()
    created_at = serializers.DateTimeField()

class PermissionsSerializer(serializers.Serializer):
    role = serializers.CharField()
    permissions = serializers.ListField(
        child=serializers.CharField()
    )

class WorkspaceSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    role = serializers.CharField()



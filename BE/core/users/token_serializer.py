from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

from users.models import UserRole

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # Accept either username or email as the login identifier.
        identifier = str(attrs.get(self.username_field, "")).strip()
        matched_user = None
        if "@" in identifier:
            matched_user = User.objects.filter(email__iexact=identifier).first()
        elif identifier:
            matched_user = User.objects.filter(username__iexact=identifier).first()

        if matched_user:
            attrs[self.username_field] = matched_user.get_username()

        data = super().validate(attrs)

        roles = list(
            UserRole.objects.filter(user=self.user, tenant=self.user.tenant)
            .values_list("role__name", flat=True)
        )
        data["roles"] = roles
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        token["tenant_id"] = str(user.tenant_id)

        return token

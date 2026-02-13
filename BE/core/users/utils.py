from users.models import Role


def user_has_role(user, role_name: str) -> bool:
    # Handle AnonymousUser safely
    if not user or not user.is_authenticated:
        return False

    return user.user_roles.filter(role__name=role_name).exists()


def is_admin(user):
    if not user or not user.is_authenticated:
        return False

    return user.user_roles.filter(
        tenant=user.tenant,
        role__name="ADMIN"
    ).exists()
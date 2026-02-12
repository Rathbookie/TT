from django.http import JsonResponse
from context.models import Tenant


class TenantMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Skip unauthenticated requests
        if not request.user.is_authenticated:
            return self.get_response(request)

        user = request.user

        if not hasattr(user, "tenant") or not user.tenant:
            return JsonResponse({"error": "User has no tenant"}, status=403)

        tenant = user.tenant

        if tenant.status != "active":
            return JsonResponse({"error": "Tenant suspended"}, status=403)

        request.tenant = tenant
        request.tenant_id = tenant.id

        return self.get_response(request)

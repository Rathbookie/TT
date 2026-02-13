from rest_framework.test import APITestCase
from rest_framework import status

from users.models import User, Role, UserRole
from context.models import Tenant
from core_api.models import Task


class TaskPermissionTests(APITestCase):

    def setUp(self):
        # --------------------
        # Tenants
        # --------------------
        self.tenant_a = Tenant.objects.create(
            name="Tenant A",
            slug="tenant-a-test"
        )

        self.tenant_b = Tenant.objects.create(
            name="Tenant B",
            slug="tenant-b-test"
        )

        # --------------------
        # Roles
        # --------------------
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.creator_role, _ = Role.objects.get_or_create(name=Role.TASK_CREATOR)
        self.receiver_role, _ = Role.objects.get_or_create(name=Role.TASK_RECEIVER)

        # --------------------
        # Users (Tenant A)
        # --------------------
        self.admin = User.objects.create_user(
            username="admin",
            password="pass123",
            tenant=self.tenant_a,
        )
        UserRole.objects.create(
            user=self.admin,
            role=self.admin_role,
            tenant=self.tenant_a,
        )

        self.creator = User.objects.create_user(
            username="creator",
            password="pass123",
            tenant=self.tenant_a,
        )
        UserRole.objects.create(
            user=self.creator,
            role=self.creator_role,
            tenant=self.tenant_a,
        )

        self.receiver = User.objects.create_user(
            username="receiver",
            password="pass123",
            tenant=self.tenant_a,
        )
        UserRole.objects.create(
            user=self.receiver,
            role=self.receiver_role,
            tenant=self.tenant_a,
        )

        self.no_role_user = User.objects.create_user(
            username="norole",
            password="pass123",
            tenant=self.tenant_a,
        )

        # --------------------
        # Cross-tenant user
        # --------------------
        self.other_user = User.objects.create_user(
            username="other",
            password="pass123",
            tenant=self.tenant_b,
        )

        self.url = "/api/tasks/"

    # --------------------
    # AUTH TESTS
    # --------------------

    def test_unauthenticated_user_cannot_access_tasks(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --------------------
    # ROLE TESTS
    # --------------------

    def test_receiver_cannot_create_task(self):
        self.client.force_authenticate(user=self.receiver)

        response = self.client.post(self.url, {
            "title": "Illegal task",
            "description": "Should fail",
            "assigned_to": self.receiver.id,
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_create_task(self):
        self.client.force_authenticate(user=self.creator)

        response = self.client.post(self.url, {
            "title": "Valid task",
            "description": "Should work",
            "assigned_to": self.receiver.id,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Task.objects.count(), 1)

    # --------------------
    # TENANT ISOLATION
    # --------------------

    def test_user_cannot_see_other_tenant_tasks(self):
        Task.objects.create(
            tenant=self.tenant_b,
            title="Other Tenant Task",
            description="",
            created_by=self.other_user,
            assigned_to=self.other_user,
        )

        self.client.force_authenticate(user=self.creator)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_user_cannot_update_other_tenant_task(self):
        task = Task.objects.create(
            tenant=self.tenant_b,
            title="Other Tenant Task",
            description="",
            created_by=self.other_user,
            assigned_to=self.other_user,
        )

        self.client.force_authenticate(user=self.creator)

        response = self.client.patch(
            f"{self.url}{task.id}/",
            {"title": "Hacked"},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_sees_all_tasks_in_same_tenant(self):
        Task.objects.create(
            tenant=self.tenant_a,
            title="Task 1",
            description="",
            created_by=self.creator,
            assigned_to=self.receiver,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

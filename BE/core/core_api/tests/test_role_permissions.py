from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from users.models import User, Role, UserRole
from core_api.models import Task
from context.models import Tenant


class RolePermissionTests(APITestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Org")

        self.creator = User.objects.create_user(
            username="creator",
            password="pass123",
            tenant=self.tenant,
        )

        self.receiver = User.objects.create_user(
            username="receiver",
            password="pass123",
            tenant=self.tenant,
        )

        self.admin = User.objects.create_user(
            username="admin",
            password="pass123",
            tenant=self.tenant,
        )

        creator_role = Role.objects.create(name="TASK_CREATOR")
        receiver_role = Role.objects.create(name="TASK_RECEIVER")
        admin_role = Role.objects.create(name="ADMIN")

        UserRole.objects.create(user=self.creator, tenant=self.tenant, role=creator_role)
        UserRole.objects.create(user=self.receiver, tenant=self.tenant, role=receiver_role)
        UserRole.objects.create(user=self.admin, tenant=self.tenant, role=admin_role)

        self.task = Task.objects.create(
            tenant=self.tenant,
            title="Test Task",
            description="Desc",
            created_by=self.creator,
            assigned_to=self.receiver,
            status="IN_PROGRESS",
            version=1,
        )

    # -------------------------
    # CREATE TESTS
    # -------------------------

    def test_receiver_cannot_create_task(self):
        self.client.force_authenticate(user=self.receiver)

        response = self.client.post(
            reverse("tasks-list"),
            {
                "title": "New Task",
                "description": "Test",
                "assigned_to": self.receiver.id,
                "status": "IN_PROGRESS",
                "version": 1,
            },
            HTTP_X_ACTIVE_ROLE="TASK_RECEIVER"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_create_task(self):
        self.client.force_authenticate(user=self.creator)

        response = self.client.post(
            reverse("tasks-list"),
            {
                "title": "New Task",
                "description": "Test",
                "assigned_to_id": self.receiver.id,
                "status": "IN_PROGRESS",
                "version": 1,
            },
            HTTP_X_ACTIVE_ROLE="TASK_CREATOR"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # -------------------------
    # UPDATE TESTS
    # -------------------------

    def test_receiver_cannot_update_task(self):
        self.client.force_authenticate(user=self.receiver)

        response = self.client.patch(
            reverse("tasks-detail", args=[self.task.id]),
            {"title": "Hacked", "version": self.task.version},
            HTTP_X_ACTIVE_ROLE="TASK_RECEIVER"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_update_own_task(self):
        self.client.force_authenticate(user=self.creator)

        response = self.client.patch(
            reverse("tasks-detail", args=[self.task.id]),
            {"title": "Updated", "version": self.task.version},
            HTTP_X_ACTIVE_ROLE="TASK_CREATOR"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -------------------------
    # DELETE TESTS
    # -------------------------

    def test_receiver_cannot_delete_task(self):
        self.client.force_authenticate(user=self.receiver)

        response = self.client.delete(
            reverse("tasks-detail", args=[self.task.id]),
            HTTP_X_ACTIVE_ROLE="TASK_RECEIVER"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_delete_task(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(
            reverse("tasks-detail", args=[self.task.id]),
            HTTP_X_ACTIVE_ROLE="ADMIN"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # -------------------------
    # SPOOF TEST
    # -------------------------

    def test_invalid_role_header_denied(self):
        self.client.force_authenticate(user=self.receiver)

        response = self.client.get(
            reverse("tasks-list"),
            HTTP_X_ACTIVE_ROLE="ADMIN"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

from rest_framework.test import APITestCase
from rest_framework import status

from users.models import User, Role, UserRole
from core_api.models import Task


class TaskPermissionTests(APITestCase):

    def setUp(self):
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.creator_role, _ = Role.objects.get_or_create(name=Role.TASK_CREATOR)
        self.receiver_role, _ = Role.objects.get_or_create(name=Role.TASK_RECEIVER)

        self.admin = User.objects.create_user(username="admin", password="pass123")
        UserRole.objects.create(user=self.admin, role=self.admin_role)

        self.creator = User.objects.create_user(username="creator", password="pass123")
        UserRole.objects.create(user=self.creator, role=self.creator_role)

        self.receiver = User.objects.create_user(username="receiver", password="pass123")
        UserRole.objects.create(user=self.receiver, role=self.receiver_role)

        self.no_role_user = User.objects.create_user(username="norole", password="pass123")

        self.url = "/api/tasks/"

    def test_unauthenticated_user_cannot_access_tasks(self):
    	self.client.force_authenticate(user=None)

    	response = self.client.get(self.url)
    	self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    def test_authenticated_user_with_no_role_sees_empty_list(self):
        self.client.force_authenticate(user=self.no_role_user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

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

    def test_admin_sees_all_tasks(self):
        Task.objects.create(
            title="Task 1",
            description="",
            created_by=self.creator,
            assigned_to=self.receiver,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

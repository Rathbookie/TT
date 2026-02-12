ROLE_PERMISSIONS = {
    "admin": [
        "tasks.read",
        "tasks.write",
        "users.read",
        "users.write",
    ],
    "manager": [
        "tasks.read",
        "tasks.write",
    ],
    "user": [
        "tasks.read",
    ],
}
from django.test import TestCase

# Create your tests here.

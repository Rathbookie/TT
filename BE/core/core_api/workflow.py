from rest_framework.exceptions import PermissionDenied

ALLOWED_TRANSITIONS = {
    "Not Started": {
        "In Progress": ["TASK_RECEIVER", "TASK_CREATOR"],
        "Cancelled": ["TASK_RECEIVER", "TASK_CREATOR", "ADMIN"],
    },
    "In Progress": {
        "Blocked": ["TASK_RECEIVER", "TASK_CREATOR"],
        "In Review": ["TASK_RECEIVER", "TASK_CREATOR"],
        "Cancelled": ["TASK_RECEIVER", "TASK_CREATOR", "ADMIN"],
    },
    "Blocked": {
        "In Progress": ["TASK_RECEIVER"],
        "Cancelled": ["TASK_RECEIVER", "TASK_CREATOR", "ADMIN"],
    },
    "In Review": {
        "Done": ["TASK_CREATOR"],
        "In Progress": ["TASK_CREATOR"],
        "Cancelled": ["TASK_CREATOR", "ADMIN"],
    },
    "Done": {
        "In Progress": ["ADMIN"],
        "Cancelled": ["ADMIN"],
    },
    "Cancelled": {},
}


def validate_transition(current_status, new_status, role):
    allowed = ALLOWED_TRANSITIONS.get(current_status, {})
    roles = allowed.get(new_status)

    if not roles:
        raise PermissionDenied("Invalid status transition.")

    if role not in roles:
        raise PermissionDenied("Role not allowed for this transition.")

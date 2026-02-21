from rest_framework.exceptions import PermissionDenied

ALLOWED_TRANSITIONS = {
    "NOT_STARTED": {
        "IN_PROGRESS": ["TASK_RECEIVER","TASK_CREATOR"],
        "CANCELLED": ["TASK_CREATOR", "ADMIN"],
    },
    "IN_PROGRESS": {
        "BLOCKED": ["TASK_RECEIVER","TASK_CREATOR"],
        "WAITING_REVIEW": ["TASK_RECEIVER","TASK_CREATOR"],
    },
    "BLOCKED": {
        "IN_PROGRESS": ["TASK_RECEIVER"],
    },
    "WAITING_REVIEW": {
        "DONE": ["TASK_CREATOR"],
        "IN_PROGRESS": ["TASK_CREATOR"],
    },
    "DONE": {},
    "CANCELLED": {},
}


def validate_transition(current_status, new_status, role):
    allowed = ALLOWED_TRANSITIONS.get(current_status, {})
    roles = allowed.get(new_status)

    if not roles:
        raise PermissionDenied("Invalid status transition.")

    if role not in roles:
        raise PermissionDenied("Role not allowed for this transition.")

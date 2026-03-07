from users.models import User

from core_api.models import Notification, Task


def _full_name(user):
    if not user:
        return "Someone"
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email or user.username or "Someone"


def create_notification(*, recipient, actor, task, kind, title, body=""):
    if not recipient or not recipient.is_active:
        return None
    if actor and recipient.id == actor.id:
        return None
    return Notification.objects.create(
        tenant=recipient.tenant,
        user=recipient,
        actor=actor,
        task=task,
        kind=kind,
        title=title[:160],
        body=(body or "")[:255],
    )


def notify_task_assigned(*, task: Task, actor: User, recipients):
    actor_name = _full_name(actor)
    for recipient in recipients:
        if not getattr(recipient, "notify_task_assigned", True):
            continue
        create_notification(
            recipient=recipient,
            actor=actor,
            task=task,
            kind=Notification.Kind.TASK_ASSIGNED,
            title=f"Assigned: {task.title}",
            body=f"{actor_name} assigned you to {task.ref_id}.",
        )


def notify_status_changed(*, task: Task, actor: User, from_status: str, to_status: str, recipients):
    actor_name = _full_name(actor)
    for recipient in recipients:
        if not getattr(recipient, "notify_task_status_changed", True):
            continue
        create_notification(
            recipient=recipient,
            actor=actor,
            task=task,
            kind=Notification.Kind.TASK_STATUS_CHANGED,
            title=f"Status changed: {task.title}",
            body=f"{actor_name} moved {task.ref_id} from {from_status or 'Unknown'} to {to_status or 'Unknown'}.",
        )


def notify_proof_submitted(*, task: Task, actor: User, recipients):
    actor_name = _full_name(actor)
    for recipient in recipients:
        if not getattr(recipient, "notify_proof_submitted", True):
            continue
        create_notification(
            recipient=recipient,
            actor=actor,
            task=task,
            kind=Notification.Kind.TASK_PROOF_SUBMITTED,
            title=f"Proof submitted: {task.title}",
            body=f"{actor_name} submitted proof on {task.ref_id}.",
        )


def notify_task_completed(*, task: Task, actor: User, recipients):
    actor_name = _full_name(actor)
    for recipient in recipients:
        if not getattr(recipient, "notify_task_status_changed", True):
            continue
        create_notification(
            recipient=recipient,
            actor=actor,
            task=task,
            kind=Notification.Kind.TASK_COMPLETED,
            title=f"Task completed: {task.title}",
            body=f"{actor_name} marked {task.ref_id} as done.",
        )

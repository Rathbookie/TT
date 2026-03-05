"""
core_api/signals.py

Signals registered here:

1. post_save on Tenant
   → Creates OrganizationProfile (task_sequence=0, plan="free")
   → Tenant already has slug — no slug generation needed here

2. post_save on Board
   → Creates 6 default BoardStatus rows for the new board
   → Uses bulk_create for efficiency (one DB round-trip)

Connected in CoreApiConfig.ready() inside apps.py.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


# =============================================================================
# SIGNAL 1: OrganizationProfile on Tenant creation
# =============================================================================

@receiver(post_save, sender="context.Tenant")
def create_organization_profile(sender, instance, created, **kwargs):
    """
    Auto-creates an OrganizationProfile when a new Tenant is created.
    Tenant.slug already exists and is unique — we just link to it.
    """
    if not created:
        return

    from core_api.models import OrganizationProfile

    # Use get_or_create as a safety net for idempotency
    OrganizationProfile.objects.get_or_create(
        tenant=instance,
        defaults={
            "task_sequence": 0,
            "plan": "free",
        },
    )


# =============================================================================
# SIGNAL 2: Default BoardStatuses on Board creation
# =============================================================================

# Default status set. Mirrors a sensible real-world workflow.
# Colors are chosen to be readable on both light and dark UIs.
# Order determines Kanban column position (left → right).

DEFAULT_BOARD_STATUSES = [
    {
        "name": "Not Started",
        "color": "#6B7280",   # gray
        "order": 0,
        "is_terminal": False,
        "is_cancelled": False,
        "is_default": True,
    },
    {
        "name": "In Progress",
        "color": "#3B82F6",   # blue
        "order": 1,
        "is_terminal": False,
        "is_cancelled": False,
        "is_default": True,
    },
    {
        "name": "Blocked",
        "color": "#EF4444",   # red
        "order": 2,
        "is_terminal": False,
        "is_cancelled": False,
        "is_default": True,
    },
    {
        "name": "In Review",
        "color": "#F59E0B",   # amber
        "order": 3,
        "is_terminal": False,
        "is_cancelled": False,
        "is_default": True,
    },
    {
        "name": "Done",
        "color": "#10B981",   # emerald
        "order": 4,
        "is_terminal": True,
        "is_cancelled": False,
        "is_default": True,
    },
    {
        "name": "Cancelled",
        "color": "#9CA3AF",   # gray-light
        "order": 5,
        "is_terminal": True,
        "is_cancelled": True,
        "is_default": True,
    },
]


@receiver(post_save, sender="core_api.Board")
def create_default_board_statuses(sender, instance, created, **kwargs):
    """
    Auto-creates the default set of BoardStatus rows for every new board.
    Uses bulk_create with ignore_conflicts=True for safety and efficiency.
    """
    if not created:
        return

    from core_api.models import BoardStatus

    statuses = [
        BoardStatus(board=instance, **data)
        for data in DEFAULT_BOARD_STATUSES
    ]

    BoardStatus.objects.bulk_create(statuses, ignore_conflicts=True)
from django.core.management.base import BaseCommand

from workflows.models import (
    WorkflowPreset,
    WorkflowPresetStage,
    WorkflowPresetWidget,
    ModuleDefinition,
)


PRESETS = [
    {
        "slug": "simple-team",
        "title": "Simple Team Workflow",
        "description": "Perfect for small teams managing tasks with basic stages and approvals",
        "color": "blue",
        "stages": ["Backlog", "In Progress", "Review", "Done"],
        "widgets": ["My Tasks", "Team Activity", "Completion Rate"],
    },
    {
        "slug": "marketing-campaign",
        "title": "Marketing Campaign",
        "description": "Track campaigns from planning to launch with content approvals",
        "color": "purple",
        "stages": ["Planning", "Content", "Review", "Scheduled", "Live"],
        "widgets": ["Campaign Status", "Content Pipeline", "Analytics"],
    },
    {
        "slug": "professional-services",
        "title": "Professional Services",
        "description": "Client project management with deliverables and milestone tracking",
        "color": "emerald",
        "stages": ["Scoping", "Active", "Client Review", "Delivered"],
        "widgets": ["Client Projects", "Billable Hours", "Deliverables"],
    },
    {
        "slug": "audit-compliance",
        "title": "Audit & Compliance",
        "description": "Evidence collection, risk assessment, and compliance tracking",
        "color": "amber",
        "stages": ["Planning", "Evidence", "Assessment", "Reporting"],
        "widgets": ["Risk Register", "Evidence Library", "Audit Trail"],
    },
]

MODULES = [
    {
        "key": "approvals",
        "name": "Approvals",
        "description": "Role-based approvals and multi-stage review processes",
        "category": "Workflow",
    },
    {
        "key": "audit-trail",
        "name": "Audit Trail",
        "description": "Complete activity logging and compliance tracking",
        "category": "Compliance",
    },
    {
        "key": "time-tracking",
        "name": "Time Tracking",
        "description": "Track effort and billable hours by task and stage",
        "category": "Productivity",
    },
    {
        "key": "risk-register",
        "name": "Risk Register",
        "description": "Assess and monitor project risks",
        "category": "Compliance",
    },
    {
        "key": "document-versioning",
        "name": "Document Versioning",
        "description": "Attachment version control and change tracking",
        "category": "Collaboration",
    },
    {
        "key": "custom-fields",
        "name": "Custom Fields",
        "description": "Dynamic custom fields and validation rules",
        "category": "Customization",
    },
]


class Command(BaseCommand):
    help = "Seed WorkOS preset and module catalog."

    def handle(self, *args, **options):
        created_presets = 0
        created_modules = 0

        for preset_data in PRESETS:
            preset, created = WorkflowPreset.objects.get_or_create(
                slug=preset_data["slug"],
                defaults={
                    "title": preset_data["title"],
                    "description": preset_data["description"],
                    "color": preset_data["color"],
                    "is_active": True,
                },
            )
            if created:
                created_presets += 1

            preset.title = preset_data["title"]
            preset.description = preset_data["description"]
            preset.color = preset_data["color"]
            preset.is_active = True
            preset.save(
                update_fields=[
                    "title",
                    "description",
                    "color",
                    "is_active",
                ]
            )

            preset.stages.all().delete()
            for idx, stage_name in enumerate(preset_data["stages"]):
                WorkflowPresetStage.objects.create(
                    preset=preset,
                    name=stage_name,
                    order=idx,
                )

            preset.widgets.all().delete()
            for idx, widget_name in enumerate(preset_data["widgets"]):
                WorkflowPresetWidget.objects.create(
                    preset=preset,
                    name=widget_name,
                    order=idx,
                )

        for module_data in MODULES:
            _, created = ModuleDefinition.objects.update_or_create(
                key=module_data["key"],
                defaults={
                    "name": module_data["name"],
                    "description": module_data["description"],
                    "category": module_data["category"],
                    "is_active": True,
                },
            )
            if created:
                created_modules += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded WorkOS catalog. Presets created: {created_presets}, "
                f"Modules created: {created_modules}"
            )
        )


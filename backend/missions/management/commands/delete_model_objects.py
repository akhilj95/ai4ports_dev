from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import transaction

class Command(BaseCommand):
    help = "Delete all objects of a given model in batches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            type=str,
            required=True,
            help="Django model name in app_label.ModelName format, e.g., missions.FrameIndex"
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of objects to delete per batch (default: 1000)."
        )

    def handle(self, *args, **options):
        model_label = options["model"]
        batch_size = options["batch_size"]

        try:
            model = apps.get_model(model_label)
        except LookupError:
            raise CommandError(f"Model '{model_label}' not found.")

        total_deleted = 0
        while True:
            with transaction.atomic():
                # Get a batch of primary keys
                pks = list(model.objects.values_list('pk', flat=True)[:batch_size])
                if not pks:
                    break
                # Delete by primary keys
                deleted_count, _ = model.objects.filter(pk__in=pks).delete()
                total_deleted += deleted_count
                self.stdout.write(f"Deleted {deleted_count} objects from {model_label} (Total deleted: {total_deleted})")

        self.stdout.write(self.style.SUCCESS(f"Completed deleting {total_deleted} objects from {model_label}."))

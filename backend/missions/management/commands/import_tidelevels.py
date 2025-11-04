from django.core.management.base import BaseCommand, CommandError
from datetime import datetime
from django.utils.timezone import make_aware
from django.db import transaction
from missions.models import TideLevel
from zoneinfo import ZoneInfo  # Python 3.9+

AZORES_TZ = ZoneInfo("Atlantic/Azores")

class Command(BaseCommand):
    help = 'Import tide level data from a text file'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to the tide data file')
        parser.add_argument(
            '--port',
            type=str,
            choices=[choice[0] for choice in TideLevel.PortChoice.choices],
            default='ponta_delgada',
            help='Port name (default: ponta_delgada)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force overwrite existing tide data within the import date range',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Batch size for bulk_create to limit memory usage (default: 1000)'
        )

    def handle(self, *args, **options):
        filepath = options['filepath']
        port_name = options['port']
        force = options['force']
        batch_size = options['batch_size']

        self.stdout.write(f"Importing tide data from {filepath} for port {port_name}")

        with open(filepath, 'r') as file:
            lines = file.readlines()

        datetimes = []
        new_entries = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) != 3:
                self.stdout.write(self.style.WARNING(f"Skipping malformed line: {line}"))
                continue
            date_str, time_str, height_str = parts
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                dt_aware = make_aware(dt, AZORES_TZ)
            except ValueError:
                self.stdout.write(self.style.WARNING(f"Skipping line with invalid date/time: {line}"))
                continue
            try:
                height = float(height_str)
            except ValueError:
                self.stdout.write(self.style.WARNING(f"Invalid tide height value, skipping line: {line}"))
                continue

            datetimes.append(dt_aware)
            new_entries.append(TideLevel(port_name=port_name, time=dt_aware, tide_height_m=height))

        if not datetimes:
            self.stdout.write(self.style.ERROR("No valid tide data found in the file"))
            return

        min_datetime = min(datetimes)
        max_datetime = max(datetimes)

        existing_qs = TideLevel.objects.filter(port_name=port_name, time__range=(min_datetime, max_datetime))

        if existing_qs.exists() and not force:
            raise CommandError(
                f"Tide data already exists from {min_datetime} to {max_datetime} for port '{port_name}'. "
                "Use --force to overwrite."
            )

        with transaction.atomic():
            if force:
                existing_qs.delete()
        
            # Insert entries in batches
            for i in range(0, len(new_entries), batch_size):
                batch = new_entries[i:i + batch_size]
                TideLevel.objects.bulk_create(batch, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS(f"Successfully imported {len(new_entries)} tide level entries."))
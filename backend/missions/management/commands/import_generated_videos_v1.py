import os
import sys
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction

from missions.models import MediaAsset

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Scans session folders for generated video files (.mp4) and links them to existing Image Set assets.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-root', 
            type=str, 
            required=True, 
            help='Path to the mission data folder containing the camera folder.'
        )
        parser.add_argument(
            '--camera-folder', 
            type=str, 
            default="camera_1", 
            help='Name of the camera folder to scan (default: "camera_1").'
        )
        parser.add_argument(
            '--yes', 
            action='store_true', 
            help='Skip confirmation prompt and proceed automatically.'
        )
        parser.add_argument(
            '--dry-run', 
            action='store_true', 
            help='Run the script without saving changes to the database.'
        )

    def handle(self, *args, **options):
        data_root_str = options['data_root']
        camera_folder_name = options['camera_folder']
        skip_confirm = options.get('yes', False)
        is_dry_run = options.get('dry_run', False)

        if is_dry_run:
            self.stdout.write(self.style.WARNING("!!! DRY RUN MODE: No changes will be saved !!!"))

        # --- 1. Path Setup ---
        input_path = Path(data_root_str)
        if input_path.is_absolute():
            data_path = input_path.resolve()
        else:
            data_path = (settings.PROJECT_DIR / input_path).resolve()

        if not data_path.exists():
             raise CommandError(f"Data root path does not exist: {data_path}")

        camera_path = data_path / camera_folder_name
        if not camera_path.exists():
             raise CommandError(f"Camera folder not found: {camera_path}")

        self.stdout.write(f"Scanning directory: {camera_path}")

        # Find all session directories
        session_dirs = sorted([
            d for d in camera_path.iterdir() 
            if d.is_dir() and d.name.startswith("session_")
        ])

        if not session_dirs:
             raise CommandError(f"No 'session_*' directories found in {camera_path}.")

        # --- 2. Scan for Videos ---
        updates_found = []

        for session_dir in session_dirs:
            # Expected video name format: session_X.mp4 inside session_X folder
            video_filename = f"{session_dir.name}.mp4"
            video_path = session_dir / video_filename

            if video_path.exists():
                # Verify relative path for DB
                try:
                    rel_video_path = str(video_path.resolve().relative_to(settings.PROJECT_DIR.resolve()))
                    rel_session_path = str(session_dir.resolve().relative_to(settings.PROJECT_DIR.resolve()))
                except ValueError:
                    self.stdout.write(self.style.ERROR(f"Skipping {session_dir.name}: Path outside project root"))
                    continue

                updates_found.append({
                    'session_name': session_dir.name,
                    'session_path': rel_session_path,
                    'video_path': rel_video_path,
                    'abs_video_path': video_path
                })

        if not updates_found:
            self.stdout.write(self.style.WARNING("No generated videos found matching the pattern 'session_X/session_X.mp4'"))
            return

        self.stdout.write(f"Found {len(updates_found)} generated videos.")

        # --- 3. Match with DB Assets ---
        matched_updates = []
        
        for item in updates_found:
            # Look for the Image Set that corresponds to this folder
            # We match strictly on the file_path stored in MediaAsset
            qs = MediaAsset.objects.filter(
                file_path=item['session_path'],
                media_type=MediaAsset.MediaType.IMAGE_SET
            )

            if qs.exists():
                asset = qs.first()
                # Check if it actually needs updating
                if asset.generated_video_path != item['video_path']:
                    matched_updates.append((asset, item['video_path']))
                else:
                    # Already linked
                    pass 
            else:
                self.stdout.write(self.style.WARNING(f"Skipping video {item['session_name']}: No matching Image Set asset found in DB."))

        if not matched_updates:
            self.stdout.write(self.style.SUCCESS("All found videos are already linked in the database."))
            return

        # --- 4. Confirmation ---
        self.stdout.write("-" * 40)
        self.stdout.write(f"Pending Updates: {len(matched_updates)}")
        self.stdout.write("-" * 40)
        for asset, vid_path in matched_updates[:5]:
            self.stdout.write(f"Link: {asset.file_path} -> {Path(vid_path).name}")
        if len(matched_updates) > 5:
            self.stdout.write(f"... and {len(matched_updates) - 5} more.")
        self.stdout.write("-" * 40)

        if not skip_confirm and not is_dry_run:
            confirm = input("Proceed with updates? [y/N]: ")
            if confirm.lower() not in ['y', 'yes']:
                sys.exit(0)

        # --- 5. Apply Updates ---
        success_count = 0
        with transaction.atomic():
            for asset, vid_path in matched_updates:
                if is_dry_run:
                    self.stdout.write(f"[DRY] Would update asset {asset.id} with {vid_path}")
                else:
                    asset.generated_video_path = vid_path
                    asset.save(update_fields=['generated_video_path'])
                    success_count += 1

        if not is_dry_run:
            self.stdout.write(self.style.SUCCESS(f"Successfully linked {success_count} videos."))
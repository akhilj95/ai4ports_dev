import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from bisect import bisect_left

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db.models import Q
from django.db import transaction

from missions.models import Mission, Sensor, SensorDeployment, MediaAsset, FrameIndex, NavSample

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Auto-detect mission, import Panasonic Image Sets, and populate FrameIndex.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-root', 
            type=str, 
            required=True, 
            help='Path to the mission data folder containing the camera folder.'
        )
        parser.add_argument(
            '--sensor-name', 
            type=str, 
            default="Panasonic_BGH1",
            help='Name of the Sensor model (default: "Panasonic_BGH1").'
        )
        parser.add_argument(
            '--sensor-instance', 
            type=int, 
            default=1,
            help='Instance number (default: 1).'
        )
        parser.add_argument(
            '--camera-folder', 
            type=str, 
            default="camera_1", 
            help='Name of the intermediate camera folder (default: "camera_1").'
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
        sensor_name = options['sensor_name']
        instance_num = options['sensor_instance']
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
             raise CommandError(f"Expected camera folder not found: {camera_path}")

        self.stdout.write(f"Scanning directory: {camera_path}")

        session_dirs = sorted([
            d for d in camera_path.iterdir() 
            if d.is_dir() and d.name.startswith("session_")
        ])

        if not session_dirs:
             raise CommandError(f"No 'session_*' directories found in {camera_path}.")

        # --- 2. Mission Auto-Detection ---
        sample_dt = self.get_sample_timestamp(session_dirs[0])
        if not sample_dt:
             raise CommandError("Could not extract a valid timestamp from the data files.")
        
        candidates = Mission.objects.filter(
            Q(start_time__lte=sample_dt) & 
            (Q(end_time__gte=sample_dt) | Q(end_time__isnull=True))
        )

        if candidates.count() == 0:
            raise CommandError(f"No Mission found covering the time {sample_dt}.")
        elif candidates.count() > 1:
            raise CommandError(f"Ambiguous! Multiple missions match this time: {candidates}")
        
        mission = candidates.first()

        # --- 3. Interactive Confirmation ---
        self.stdout.write(self.style.SUCCESS("-" * 40))
        self.stdout.write(self.style.SUCCESS("MATCH FOUND"))
        self.stdout.write(self.style.SUCCESS("-" * 40))
        self.stdout.write(f"Mission:   {mission.pk} - {mission.location}")
        self.stdout.write(f"Date:      {mission.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.stdout.write("-" * 40)
        self.stdout.write(f"Sensor:    {sensor_name} (Instance {instance_num})")
        self.stdout.write("-" * 40)

        if not skip_confirm and not is_dry_run:
            confirm = input("Proceed with import? [y/N]: ")
            if confirm.lower() not in ['y', 'yes']:
                sys.exit(0)

        # --- 4. Load Deployment & Nav Data ---
        try:
            sensor = Sensor.objects.get(name=sensor_name)
            deployment = SensorDeployment.objects.get(
                mission=mission,
                sensor=sensor,
                instance=instance_num
            )
        except (Sensor.DoesNotExist, SensorDeployment.DoesNotExist) as e:
            raise CommandError(f"Deployment lookup failed: {e}")

        # PRE-LOAD NavSamples for efficiency (used for FrameIndex matching)
        self.stdout.write("Loading NavSamples for matching...")
        nav_samples = list(
            NavSample.objects.filter(mission=mission)
            .order_by('timestamp')
            .values('id', 'timestamp')
        )
        self.stdout.write(f"Loaded {len(nav_samples)} NavSamples.")

        # --- 5. Process Sessions ---
        processed_count = 0
        for session_dir in session_dirs:
            try:
                self.process_session(session_dir, deployment, nav_samples, is_dry_run)
                processed_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed session {session_dir.name}: {e}"))
                logger.error(f"Failed session {session_dir.name}", exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"Done. Imported {processed_count} session(s)."))

    def get_sample_timestamp(self, session_dir):
        ts_files = list(session_dir.glob("*timestamp*.txt"))
        if not ts_files: return None
        try:
            with open(ts_files[0], 'r') as f:
                for line in f:
                    parts = line.strip().split(' ')
                    if len(parts) >= 2:
                        return datetime.fromtimestamp(int(parts[1]) / 1000.0, tz=timezone.utc)
        except: return None

    def process_session(self, session_dir, deployment, nav_samples, is_dry_run):
        self.stdout.write(f"--> Processing {session_dir.name}")

        # 1. Calc Path
        project_root = settings.PROJECT_DIR.resolve()
        try:
            stored_path_str = str(session_dir.resolve().relative_to(project_root))
        except ValueError:
             raise CommandError(f"Folder not in project root.")

        # 2. Parse Timestamps
        ts_files = list(session_dir.glob("*timestamp*.txt"))
        if not ts_files: raise CommandError("No timestamp file found.")
        ts_file_path = ts_files[0]

        # Store tuples of (frame_number, timestamp)
        # We assume image0 corresponds to frame_number 0
        frame_data = [] 
        
        with open(ts_file_path, 'r') as f:
            for line in f:
                stripped = line.strip()
                if not stripped: continue
                parts = stripped.split(' ')
                if len(parts) < 2: continue
                
                try:
                    # Parse "image123" -> 123
                    img_name = parts[0]
                    # Simple extraction: remove 'image' prefix, parse int
                    # If naming is just "image0", "image1"...
                    frame_num = int(img_name.replace('image', ''))
                    
                    epoch_ms = int(parts[1])
                    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
                    frame_data.append((frame_num, dt))
                except ValueError:
                    pass

        if not frame_data:
             raise CommandError("No valid data parsed from timestamp file.")

        # Sort by frame number just in case file is out of order
        frame_data.sort(key=lambda x: x[0])
        
        start_time = frame_data[0][1]
        end_time = frame_data[-1][1]
        image_count = len(frame_data)

        if is_dry_run:
            self.stdout.write(f"   [DRY] MediaAsset: {image_count} images, {start_time}-{end_time}")
            return

        # 3. Save MediaAsset
        with transaction.atomic():
            asset, created = MediaAsset.objects.update_or_create(
                deployment=deployment,
                file_path=stored_path_str,
                media_type=MediaAsset.MediaType.IMAGE_SET,
                defaults={
                    'start_time': start_time,
                    'end_time': end_time,
                    'fps': None,
                    'file_metadata': {
                        'image_count': image_count,
                        'session_folder_name': session_dir.name,
                        'timestamp_source_file': ts_file_path.name
                    },
                    'notes': f"Imported session {session_dir.name}"
                }
            )

            # 4. Populate FrameIndex (The matching logic)
            # Delete old frames if we are re-importing (to avoid duplicates/stale links)
            FrameIndex.objects.filter(media_asset=asset).delete()

            frame_batch = []
            nav_timestamps = [n['timestamp'] for n in nav_samples]
            nav_count = len(nav_samples)

            for f_num, f_ts in frame_data:
                # Binary Search for closest NavSample
                closest_nav_id = None
                time_diff_ms = None

                if nav_count > 0:
                    pos = bisect_left(nav_timestamps, f_ts)
                    if pos == 0:
                        idx = 0
                    elif pos == nav_count:
                        idx = nav_count - 1
                    else:
                        before = nav_timestamps[pos - 1]
                        after = nav_timestamps[pos]
                        if abs((f_ts - before).total_seconds()) <= abs((after - f_ts).total_seconds()):
                            idx = pos - 1
                        else:
                            idx = pos
                    
                    closest_nav_id = nav_samples[idx]['id']
                    time_diff = (f_ts - nav_samples[idx]['timestamp']).total_seconds() * 1000
                    time_diff_ms = int(abs(time_diff))

                frame_batch.append(FrameIndex(
                    media_asset=asset,
                    frame_number=f_num,
                    timestamp=f_ts,
                    closest_nav_sample_id=closest_nav_id,
                    nav_match_time_diff_ms=time_diff_ms
                ))

            # Bulk Create
            FrameIndex.objects.bulk_create(frame_batch)
            self.stdout.write(f"   [SAVED] Asset ID {asset.id} + {len(frame_batch)} FrameIndex records")
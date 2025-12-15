import os
import sys
import re
import logging
import concurrent.futures
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
    help = 'Import Sonoptix Sonar Image Sets (Optimized/Threaded) and populate FrameIndex.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-root', 
            type=str, 
            required=True, 
            help='Path to the mission data folder (should contain the "sonar" folder).'
        )
        parser.add_argument(
            '--sensor-name', 
            type=str, 
            default="SonoptixECHO",
            help='Name of the Sensor model (default: "SonoptixECHO").'
        )
        parser.add_argument(
            '--sensor-instance', 
            type=int, 
            default=0,
            help='Instance number (default: 0).'
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
        skip_confirm = options.get('yes', False)
        is_dry_run = options.get('dry_run', False)

        if is_dry_run:
            self.stdout.write(self.style.WARNING("!!! DRY RUN MODE: No changes will be saved !!!"))

        # --- 1. Path Verification ---
        input_path = Path(data_root_str)
        if input_path.is_absolute():
            mission_path = input_path.resolve()
        else:
            mission_path = (settings.PROJECT_DIR / input_path).resolve()

        if not mission_path.exists():
             raise CommandError(f"Mission root path does not exist: {mission_path}")

        sonar_root = mission_path / 'sonar'
        images_root = sonar_root / 'images'
        raw_root = sonar_root / 'raw'

        if not images_root.exists(): raise CommandError(f"Expected folder not found: {images_root}")
        if not raw_root.exists(): raise CommandError(f"Expected folder not found: {raw_root}")

        self.stdout.write(f"Scanning Sonar Data: {sonar_root}")

        image_sessions = sorted([
            d for d in images_root.iterdir() 
            if d.is_dir() and d.name.startswith("session_")
        ])

        if not image_sessions:
             raise CommandError(f"No 'session_*' directories found in {images_root}.")

        # --- 2. Mission Auto-Detection ---
        # Find first valid raw session to get timestamp
        sample_dt = None
        for sess in image_sessions:
             raw_sess = raw_root / sess.name
             if raw_sess.exists():
                 sample_dt = self.get_sample_timestamp(raw_sess)
                 if sample_dt: break
        
        if not sample_dt:
             raise CommandError("Could not extract a valid timestamp from any raw files.")
        
        self.stdout.write(f"Detected Timestamp: {sample_dt} (UTC)")

        candidates = Mission.objects.filter(
            Q(start_time__lte=sample_dt) & 
            (Q(end_time__gte=sample_dt) | Q(end_time__isnull=True))
        )

        if candidates.count() == 0:
            raise CommandError(f"No Mission found covering the time {sample_dt}.")
        elif candidates.count() > 1:
            raise CommandError(f"Ambiguous! Multiple missions match this time: {candidates}")
        
        mission = candidates.first()

        # --- 3. Confirmation ---
        self.stdout.write(self.style.SUCCESS("-" * 40))
        self.stdout.write(f"Mission:   {mission.pk} - {mission.location}")
        self.stdout.write(f"Date:      {mission.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.stdout.write(f"Sensor:    {sensor_name} (Instance {instance_num})")
        self.stdout.write("-" * 40)

        if not skip_confirm and not is_dry_run:
            confirm = input("Proceed? [y/N]: ")
            if confirm.lower() not in ['y', 'yes']: sys.exit(0)

        # --- 4. Load Data ---
        try:
            sensor = Sensor.objects.get(name=sensor_name)
            deployment = SensorDeployment.objects.get(
                mission=mission, sensor=sensor, instance=instance_num
            )
        except Exception as e:
            raise CommandError(f"Deployment lookup failed: {e}")

        # OPTIMIZATION: Use values_list for faster tuple access and lower memory
        self.stdout.write("Loading NavSamples (optimized)...")
        nav_data = list(NavSample.objects.filter(mission=mission)
                        .order_by('timestamp')
                        .values_list('id', 'timestamp'))
        
        # Unzip into separate lists for bisect
        if nav_data:
            nav_ids, nav_timestamps = zip(*nav_data)
        else:
            nav_ids, nav_timestamps = [], []

        # --- 5. Process Sessions ---
        processed_count = 0
        for img_session_dir in image_sessions:
            session_name = img_session_dir.name
            raw_session_dir = raw_root / session_name
            
            if not raw_session_dir.exists(): continue

            try:
                self.process_session(
                    img_session_dir, raw_session_dir, deployment, 
                    nav_ids, nav_timestamps, is_dry_run
                )
                processed_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed session {session_name}: {e}"))
                logger.error(f"Failed session {session_name}", exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"Done. Imported {processed_count} session(s)."))

    def get_sample_timestamp(self, raw_session_dir):
        # Quick check for one valid file
        txt_files = list(raw_session_dir.glob("sonoptix-frame*.txt"))
        for txt_file in txt_files:
            res = self._parse_frame_file(txt_file)
            if res: return res[1]
        return None

    def _parse_frame_file(self, file_path):
        """Helper to parse a single file. Returns (frame_num, dt) or None."""
        try:
            match = re.search(r'frame(\d+)\.txt', file_path.name)
            if not match: return None
            frame_num = int(match.group(1))

            with open(file_path, 'r') as f:
                first_line = f.readline()
                parts = first_line.strip().split(' ')
                if len(parts) >= 2:
                    epoch_ms = int(parts[1])
                    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
                    return (frame_num, dt)
        except Exception:
            return None
        return None

    def process_session(self, img_session_dir, raw_session_dir, deployment, 
                        nav_ids, nav_timestamps, is_dry_run):
        
        self.stdout.write(f"--> Processing {img_session_dir.name}")
        project_root = settings.PROJECT_DIR.resolve()
        
        try:
            stored_path_str = str(img_session_dir.resolve().relative_to(project_root))
        except ValueError:
             raise CommandError(f"Folder not in project root.")

        txt_files = list(raw_session_dir.glob("sonoptix-frame*.txt"))
        if not txt_files: raise CommandError("No text files found.")

        # --- PARALLEL PROCESSING START ---
        frame_data = []
        # Use ThreadPoolExecutor to mask I/O latency
        # Adjust max_workers based on your disk (10-20 is usually good for simple text files)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all file parsing jobs
            future_to_file = {executor.submit(self._parse_frame_file, f): f for f in txt_files}
            
            # Gather results as they complete
            for future in concurrent.futures.as_completed(future_to_file):
                result = future.result()
                if result:
                    frame_data.append(result)
        # --- PARALLEL PROCESSING END ---

        if not frame_data: raise CommandError("No valid data parsed.")
        
        frame_data.sort(key=lambda x: x[0])
        start_time, end_time = frame_data[0][1], frame_data[-1][1]
        image_count = len(frame_data)

        if is_dry_run:
            self.stdout.write(f"   [DRY] {image_count} frames, {start_time:%H:%M:%S}-{end_time:%H:%M:%S}")
            return

        with transaction.atomic():
            asset, _ = MediaAsset.objects.update_or_create(
                deployment=deployment,
                file_path=stored_path_str,
                media_type=MediaAsset.MediaType.IMAGE_SET,
                defaults={
                    'start_time': start_time, 'end_time': end_time, 'fps': None,
                    'file_metadata': {'image_count': image_count, 'raw_data_folder': raw_session_dir.name},
                    'notes': f"Imported Sonoptix session {img_session_dir.name}"
                }
            )

            # Cleanup old frames
            FrameIndex.objects.filter(media_asset=asset).delete()

            # Batch create FrameIndex
            frame_batch = []
            nav_count = len(nav_timestamps)

            for f_num, f_ts in frame_data:
                closest_nav_id = None
                time_diff_ms = None

                if nav_count > 0:
                    pos = bisect_left(nav_timestamps, f_ts)
                    idx = 0
                    if pos == 0: idx = 0
                    elif pos == nav_count: idx = nav_count - 1
                    else:
                        before = nav_timestamps[pos - 1]
                        after = nav_timestamps[pos]
                        if abs((f_ts - before).total_seconds()) <= abs((after - f_ts).total_seconds()):
                            idx = pos - 1
                        else:
                            idx = pos
                    
                    closest_nav_id = nav_ids[idx]
                    time_diff = (f_ts - nav_timestamps[idx]).total_seconds() * 1000
                    time_diff_ms = int(abs(time_diff))

                frame_batch.append(FrameIndex(
                    media_asset=asset, frame_number=f_num, timestamp=f_ts,
                    closest_nav_sample_id=closest_nav_id, nav_match_time_diff_ms=time_diff_ms
                ))

            FrameIndex.objects.bulk_create(frame_batch)
            self.stdout.write(f"   [SAVED] Asset ID {asset.id} + {len(frame_batch)} frames")
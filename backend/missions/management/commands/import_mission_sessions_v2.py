import os
import re
import logging
import cv2  # pip install opencv-python
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bisect import bisect_left

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from missions.models import Mission, Sensor, SensorDeployment, MediaAsset, FrameIndex, NavSample

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Imports V2 Session Data (Epoch timestamps). MAKE SURE MISSION, LOGS and SENSORDEPLOYMENTS ARE ALREADY CREATED.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-root', 
            type=str, 
            required=True, 
            help='Path to the date-based root folder (e.g., .../2025_12_09/).'
        )
        parser.add_argument(
            '--dry-run', 
            action='store_true', 
            help='Run logic without saving changes to the database.'
        )

    def handle(self, *args, **options):
        self.data_root = Path(options['data_root']).resolve()
        self.is_dry_run = options.get('dry_run', False)

        if not self.data_root.exists():
            raise CommandError(f"Root path not found: {self.data_root}")

        self.stdout.write(f"Scanning Root: {self.data_root.name}")

        mission_dirs = sorted([d for d in self.data_root.iterdir() if d.is_dir() and d.name.startswith("mission")])

        if not mission_dirs:
            self.stdout.write(self.style.WARNING(f"No 'mission*' folders found in {self.data_root}"))
            return

        for m_dir in mission_dirs:
            self.process_mission_folder(m_dir)

    def process_mission_folder(self, mission_dir):
        self.stdout.write(self.style.SUCCESS(f"\nScanning Mission Folder: {mission_dir.name}"))
        
        session_dirs = sorted([d for d in mission_dir.iterdir() if d.is_dir() and d.name.startswith("session")])
        if not session_dirs:
            self.stdout.write("  No sessions found.")
            return

        # 1. Identify Mission from DB using the first session's time
        reference_dt = self.extract_reference_timestamp(session_dirs[0])
        if not reference_dt:
            self.stdout.write(self.style.ERROR(f"  CRITICAL: Could not determine timestamp for {mission_dir.name}. Skipping."))
            return

        mission = self.find_mission_by_time(reference_dt)
        if not mission:
            self.stdout.write(self.style.ERROR(f"  No DB Mission found covering time {reference_dt} (UTC). Skipping."))
            return

        self.stdout.write(f"  -> Linked to Mission ID: {mission.id} ({mission.start_time})")
        
        # 2. Pre-load Nav Samples
        nav_samples = list(NavSample.objects.filter(mission=mission).order_by('timestamp').values('id', 'timestamp'))
        nav_timestamps = [n['timestamp'] for n in nav_samples]
        nav_ids = [n['id'] for n in nav_samples]

        # 3. Process Each Session
        for s_dir in session_dirs:
            self.stdout.write(f"  Processing Session: {s_dir.name}")
            
            # Determine this specific session's start time for fallback use
            session_dt = self.extract_reference_timestamp(s_dir)

            # --- IMPORTERS ---
            self.import_camera_0(mission, s_dir / "camera_0", session_dt, nav_timestamps, nav_ids)
            self.import_camera_1(mission, s_dir / "camera_1", nav_timestamps, nav_ids)
            self.import_sonar(mission, s_dir / "sonar", nav_timestamps, nav_ids)

    # -------------------------------------------------------------------------
    # 1. CAMERA 0 IMPORTER (Robust Manual Scan)
    # -------------------------------------------------------------------------
    def import_camera_0(self, mission, folder, session_start_time, nav_ts, nav_ids):
        if not folder.exists(): return

        video_files = list(folder.glob("main_rec_*.mkv")) + list(folder.glob("main_rec_*.mp4"))
        if not video_files: return

        video_path = video_files[0]
        
        # 1. Determine Start Time
        start_time_utc = None
        match = re.search(r'main_rec_(\d+)', video_path.name)
        
        if match:
            epoch_ts = int(match.group(1))
            start_time_utc = datetime.fromtimestamp(epoch_ts, tz=timezone.utc)
            self.stdout.write(f"    [INFO] Cam0: Found {video_path.name} -> {start_time_utc}")
        else:
            self.stdout.write(self.style.ERROR(f"    [ERR] Cam0: Could not parse epoch from filename. Fallback to session time."))
            start_time_utc = session_start_time

        if not start_time_utc:
             return

        # 2. Determine End Time & Stats
        end_time_utc = None
        video_fps = None
        total_frames = 0
        
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                self.stdout.write(self.style.ERROR(f"    [CV2] Error: Could not open video file {video_path}"))
            else:
                header_fps = cap.get(cv2.CAP_PROP_FPS)
                header_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)

                # FAST PATH
                if header_fps > 0 and header_count > 0:
                     duration_sec = header_count / header_fps
                     end_time_utc = start_time_utc + timedelta(seconds=duration_sec)
                     video_fps = header_fps
                     total_frames = int(header_count)
                     self.stdout.write(f"    [CV2] Metadata Valid: {duration_sec:.2f}s (FPS: {video_fps:.2f}, Frames: {total_frames})")
                
                # SLOW PATH
                else:
                    self.stdout.write(self.style.WARNING(f"    [CV2] Invalid Metadata. Deep scanning..."))
                    real_fps = header_fps if header_fps > 0 else 30.0
                    frame_count = 0
                    while True:
                        ret = cap.grab()
                        if not ret: break

                        last_timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                        frame_count += 1
                        if frame_count % 1000 == 0:
                            print(f"\r    [CV2] Scanned {frame_count} frames...", end="", flush=True)

                    print(f"\r    [CV2] Scan Complete. Found {frame_count} frames.           ")
                    
                    if frame_count > 0:
                        # Use the timestamp from the last valid frame (most accurate)
                        duration_ms = last_timestamp_ms
                        if duration_ms <= 0:
                            duration_ms = (frame_count / real_fps) * 1000.0
                        
                        duration_sec = duration_ms / 1000.0
                        end_time_utc = start_time_utc + timedelta(seconds=duration_sec)
                        
                        # --- FIX: Recalculate FPS to match observations ---
                        # Ensures frames fit exactly into the duration without drift
                        if duration_sec > 0:
                            video_fps = frame_count / duration_sec
                        else:
                            video_fps = real_fps
                        total_frames = frame_count
                        self.stdout.write(f"    [CV2] Deep Scan Duration: {duration_sec:.2f}s")

                cap.release()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    [CV2] Error probing video: {e}"))

        if not end_time_utc:
            end_time_utc = mission.end_time or (start_time_utc + timedelta(minutes=1))

        if self.is_dry_run:
            self.stdout.write(f"    [DRY] Would import {video_path.name} and index {total_frames} frames.")
            return

        # 3. Save Asset
        try:
            sensor = Sensor.objects.get(name="BR_LowLightCamera")
            deployment = SensorDeployment.objects.get(mission=mission, sensor=sensor, instance=0)
            rel_path = str(video_path.resolve().relative_to(settings.PROJECT_DIR.resolve()))
            
            with transaction.atomic():
                asset, _ = MediaAsset.objects.update_or_create(
                    deployment=deployment,
                    file_path=rel_path,
                    media_type=MediaAsset.MediaType.VIDEO,
                    defaults={
                        'start_time': start_time_utc,
                        'end_time': end_time_utc,
                        'fps': video_fps,
                        'notes': "Imported from BR_LowLightCamera (V2)"
                    }
                )

                # 4. Populate FrameIndex
                if video_fps and total_frames > 0:
                    FrameIndex.objects.filter(media_asset=asset).delete()
                    
                    batch = []
                    nav_len = len(nav_ts)
                    frame_interval = 1.0 / float(video_fps)

                    for i in range(total_frames):
                        # Calculate exact timestamp for this frame index
                        # timestamp = start + (frame_num * interval)
                        f_ts = start_time_utc + timedelta(seconds=i * frame_interval)
                        
                        # Binary Search for Nav Link (Same logic as Camera 1 / Sonar)
                        closest_id = None
                        diff = None
                        if nav_len > 0:
                            pos = bisect_left(nav_ts, f_ts)
                            idx = pos if pos < nav_len else nav_len - 1
                            if pos > 0:
                                before = nav_ts[pos-1]
                                after = nav_ts[min(pos, nav_len-1)]
                                if abs((f_ts - before).total_seconds()) <= abs((after - f_ts).total_seconds()):
                                    idx = pos - 1
                            
                            closest_id = nav_ids[idx]
                            diff = int(abs((f_ts - nav_ts[idx]).total_seconds()) * 1000)

                        batch.append(FrameIndex(
                            media_asset=asset,
                            frame_number=i,
                            timestamp=f_ts,
                            closest_nav_sample_id=closest_id,
                            nav_match_time_diff_ms=diff
                        ))

                        if len(batch) >= 2000:
                            FrameIndex.objects.bulk_create(batch, batch_size=2000)
                            batch = []

                    if batch:
                        FrameIndex.objects.bulk_create(batch, batch_size=2000)
                        self.stdout.write("    [STAT] Calculating depth stats...")
                        asset.calculate_stats()
                    
                    self.stdout.write(f"    [OK] Cam0: Saved Asset + {total_frames} FrameIndex records.")

        except Sensor.DoesNotExist:
            self.stdout.write(self.style.ERROR("    [ERR] Sensor 'BR_LowLightCamera' not found in DB."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    [ERR] Cam0 Import Failed: {e}"))

    # -------------------------------------------------------------------------
    # 2. CAMERA 1 IMPORTER
    # -------------------------------------------------------------------------
    def import_camera_1(self, mission, folder, nav_ts, nav_ids):
        if not folder.exists(): return

        ts_file = folder / "timestamps.txt"
        images_dir = folder / "images"

        if not ts_file.exists():
            self.stdout.write("    [SKIP] Cam1: timestamps.txt missing.")
            return
        
        target_path = images_dir if images_dir.exists() else folder

        frame_data = []
        try:
            with open(ts_file, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            f_num = int(parts[0].replace('image', ''))
                            dt = datetime.fromtimestamp(int(parts[1]) / 1000.0, tz=timezone.utc)
                            frame_data.append((f_num, dt))
                        except ValueError:
                            continue
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    [ERR] Cam1: Error reading timestamps: {e}"))
            return

        if frame_data:
            self._save_asset_sequence(
                mission, "Panasonic_BGH1", 1, target_path, frame_data, nav_ts, nav_ids, "Camera 1"
            )

    # -------------------------------------------------------------------------
    # 3. SONAR IMPORTER
    # -------------------------------------------------------------------------
    def import_sonar(self, mission, folder, nav_ts, nav_ids):
        if not folder.exists(): return

        raw_dir = folder / "raw"
        images_dir = folder / "images" 
        
        if not raw_dir.exists(): return

        raw_files = sorted(list(raw_dir.glob("*.txt"))) 
        if not raw_files: return

        frame_data = []
        for rf in raw_files:
            match = re.search(r'frame(\d+)\.txt', rf.name)
            if match:
                f_num = int(match.group(1))
                try:
                    with open(rf, 'r') as f:
                        line = f.readline().strip()
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            dt = datetime.fromtimestamp(int(parts[1]) / 1000.0, tz=timezone.utc)
                            frame_data.append((f_num, dt))
                except Exception:
                    continue
        
        if frame_data:
            target_path = images_dir if images_dir.exists() else folder
            self._save_asset_sequence(
                mission, "SonoptixECHO", 0, target_path, frame_data, nav_ts, nav_ids, "Sonar"
            )

    # -------------------------------------------------------------------------
    # SHARED UTILS
    # -------------------------------------------------------------------------
    def _save_asset_sequence(self, mission, sensor_name, instance, folder_path, frame_data, nav_ts, nav_ids, label):
        frame_data.sort(key=lambda x: x[0])
        start = frame_data[0][1]
        end = frame_data[-1][1]
        count = len(frame_data)

        if self.is_dry_run:
            self.stdout.write(f"    [DRY] {label}: {count} frames")
            return

        try:
            try:
                sensor = Sensor.objects.get(name=sensor_name)
                deployment = SensorDeployment.objects.get(mission=mission, sensor=sensor, instance=instance)
            except (Sensor.DoesNotExist, SensorDeployment.DoesNotExist):
                self.stdout.write(self.style.WARNING(f"    [SKIP] {label}: Sensor or Deployment not found."))
                return
            
            rel_path = str(folder_path.resolve().relative_to(settings.PROJECT_DIR.resolve()))

            with transaction.atomic():
                asset, _ = MediaAsset.objects.update_or_create(
                    deployment=deployment,
                    file_path=rel_path,
                    media_type=MediaAsset.MediaType.IMAGE_SET,
                    defaults={
                        'start_time': start,
                        'end_time': end,
                        'file_metadata': {'image_count': count},
                        'notes': f"Imported {label} (V2)"
                    }
                )

                FrameIndex.objects.filter(media_asset=asset).delete()
                batch = []
                nav_len = len(nav_ts)

                for f_num, f_ts in frame_data:
                    closest_id = None
                    diff = None
                    if nav_len > 0:
                        pos = bisect_left(nav_ts, f_ts)
                        idx = pos if pos < nav_len else nav_len - 1
                        if pos > 0:
                            before = nav_ts[pos-1]
                            after = nav_ts[min(pos, nav_len-1)]
                            if abs((f_ts - before).total_seconds()) <= abs((after - f_ts).total_seconds()):
                                idx = pos - 1
                        
                        closest_id = nav_ids[idx]
                        diff = int(abs((f_ts - nav_ts[idx]).total_seconds()) * 1000)

                    batch.append(FrameIndex(
                        media_asset=asset, frame_number=f_num, timestamp=f_ts,
                        closest_nav_sample_id=closest_id, nav_match_time_diff_ms=diff
                    ))
                
                FrameIndex.objects.bulk_create(batch, batch_size=2000)

                # Calculate min/max depth now that frames exist
                asset.calculate_stats()
                
                self.stdout.write(f"    [OK] {label}: Saved {count} frames.")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    [ERR] {label} Failed: {e}"))

    def extract_reference_timestamp(self, session_dir):
        # 1. Try Cam1
        ts_file = session_dir / "camera_1" / "timestamps.txt"
        if ts_file.exists():
            ts = self._read_first_ts(ts_file)
            if ts: return ts
        
        # 2. Try Sonar raw
        raw_files = sorted(list((session_dir / "sonar" / "raw").glob("*.txt")))
        if raw_files:
            ts = self._read_first_ts(raw_files[0])
            if ts: return ts

        # 3. Fallback: Parse Epoch from Folder Name
        match = re.search(r'session_(\d+)', session_dir.name)
        if match:
            epoch_ts = int(match.group(1))
            return datetime.fromtimestamp(epoch_ts, tz=timezone.utc)

        return None

    def _read_first_ts(self, filepath):
        try:
            with open(filepath, 'r') as f:
                parts = f.readline().strip().split()
                if len(parts) >= 2:
                    return datetime.fromtimestamp(int(parts[1]) / 1000.0, tz=timezone.utc)
        except: pass
        return None

    def find_mission_by_time(self, dt):
        return Mission.objects.filter(
            Q(start_time__lte=dt) & 
            (Q(end_time__gte=dt) | Q(end_time__isnull=True))
        ).first()
import os
import subprocess
import logging
import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Q
from missions.models import MediaAsset

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generates MP4 videos from MediaAsset Image Sets (session_EPOCH.mp4).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mission-id',
            type=int,
            help='Process only assets belonging to this specific Mission ID.'
        )
        parser.add_argument(
            '--fps',
            type=float,
            help='Force a specific framerate (default: calculates from database timestamps or uses 15.0).'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate videos even if the asset already has a video linked.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without running ffmpeg or saving changes.'
        )

    def handle(self, *args, **options):
        mission_id = options['mission_id']
        force_fps = options['fps']
        force_regen = options['force']
        is_dry_run = options['dry_run']

        # 1. Build Query
        filters = Q(media_type=MediaAsset.MediaType.IMAGE_SET)
        
        if mission_id:
            filters &= Q(deployment__mission_id=mission_id)
        
        if not force_regen:
            filters &= (Q(generated_video_path__isnull=True) | Q(generated_video_path=''))

        assets = MediaAsset.objects.filter(filters)
        
        self.stdout.write(f"Found {assets.count()} Image Sets to process.")

        for asset in assets:
            self.process_asset(asset, force_fps, is_dry_run)

    def process_asset(self, asset, force_fps, is_dry_run):
        try:
            # Resolve Base Path
            base_dir = (settings.PROJECT_DIR / asset.file_path).resolve()

            if not base_dir.exists():
                self.stdout.write(self.style.ERROR(f"  [SKIP] Folder not found: {base_dir}"))
                return

            self.stdout.write(f"--> Processing Asset {asset.id} ({asset.deployment.sensor.name})")

            # ---------------------------------------------------------
            # 1. GENERATE UNIQUE FILENAME (session_EPOCH.mp4)
            # ---------------------------------------------------------
            # Use DB start_time to ensure it matches the asset perfectly
            epoch_ts = int(asset.start_time.timestamp())
            output_filename = f"session_{epoch_ts}.mp4"
            
            output_full_path = base_dir / output_filename
            output_rel_path = str(output_full_path.relative_to(settings.PROJECT_DIR))

            # ---------------------------------------------------------
            # 2. LOCATE IMAGES
            # ---------------------------------------------------------
            # Since asset path points to the specific session folder, images should be here.
            # We still check subfolders just in case of odd structure.
            image_dir = base_dir
            
            def has_images(path):
                if not path.is_dir(): return False
                return any(f.name.endswith(('.jpg', '.png')) for f in path.iterdir() if f.is_file())

            if has_images(base_dir):
                image_dir = base_dir
            elif (base_dir / "images").exists() and has_images(base_dir / "images"):
                image_dir = base_dir / "images"
                self.stdout.write(f"     Found images in 'images/' subfolder.")
            else:
                self.stdout.write(self.style.WARNING("     [SKIP] No images found in folder."))
                return

            # ---------------------------------------------------------
            # 3. DETERMINE FRAMERATE
            # ---------------------------------------------------------
            fps = 15.0 
            if force_fps:
                fps = force_fps
            else:
                duration_sec = 0
                if asset.start_time and asset.end_time:
                    duration_sec = (asset.end_time - asset.start_time).total_seconds()
                
                frame_count = asset.file_metadata.get('image_count', 0)
                if not frame_count:
                    frame_count = asset.frames.count()

                if duration_sec > 0 and frame_count > 0:
                    fps = frame_count / duration_sec
                    if fps > 60: fps = 30.0
                
            self.stdout.write(f"     Target FPS: {fps:.2f}")

            # ---------------------------------------------------------
            # 4. DETECT PATTERN & START NUMBER
            # ---------------------------------------------------------
            files = sorted([f.name for f in image_dir.iterdir() if f.is_file()])
            pattern = None
            start_number = 0
            
            def get_start_number(prefix, ext):
                for fname in files:
                    if fname.startswith(prefix) and fname.endswith(ext):
                        match = re.search(r'(\d+)', fname)
                        if match: return int(match.group(1))
                return 0

            if any(f.startswith("image") and f.endswith(".jpg") for f in files[:5]):
                pattern = "image%d.jpg"
                start_number = get_start_number("image", ".jpg")
            elif any(f.startswith("image") and f.endswith(".png") for f in files[:5]):
                pattern = "image%d.png"
                start_number = get_start_number("image", ".png")
            elif any(f.startswith("frame") and f.endswith(".jpg") for f in files[:5]):
                pattern = "frame%d.jpg"
                start_number = get_start_number("frame", ".jpg")
            elif any(f.startswith("frame") and f.endswith(".png") for f in files[:5]):
                pattern = "frame%d.png"
                start_number = get_start_number("frame", ".png")
            
            if not pattern:
                self.stdout.write(self.style.WARNING("     [SKIP] Could not detect valid image sequence pattern."))
                return

            # ---------------------------------------------------------
            # 5. RUN FFMPEG
            # ---------------------------------------------------------
            cmd = [
                "ffmpeg",
                "-y",
                "-framerate", str(fps),
                "-start_number", str(start_number),
                "-i", str(image_dir / pattern),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_full_path)
            ]

            if is_dry_run:
                self.stdout.write(f"     [DRY] Output: {output_full_path.name}")
                self.stdout.write(f"     [DRY] Command: {' '.join(cmd)}")
            else:
                self.stdout.write(f"     Generating {output_full_path.name}...")
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    asset.generated_video_path = output_rel_path
                    asset.save(update_fields=['generated_video_path'])
                    self.stdout.write(self.style.SUCCESS(f"     [OK] Video created."))
                else:
                    self.stdout.write(self.style.ERROR(f"     [FAIL] FFmpeg error: {result.stderr}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"     [ERR] Unexpected error: {e}"))
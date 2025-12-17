import os
import cv2
import logging
from pathlib import Path
from PIL import Image
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Q
from missions.models import MediaAsset

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generates preview thumbnails for all MediaAssets (safe for V1/V2 structures).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate thumbnails even if they already exist.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without creating files or saving to DB.'
        )
        parser.add_argument(
            '--type',
            type=str,
            choices=['video', 'image', 'image_set', 'all'],
            default='all',
            help='Limit generation to a specific media type.'
        )

    def handle(self, *args, **options):
        force = options['force']
        dry_run = options['dry_run']
        target_type = options['type']

        # Filter assets based on arguments
        filters = Q()
        if not force:
            filters &= (Q(thumbnail_path__isnull=True) | Q(thumbnail_path=''))
        
        if target_type == 'video':
            filters &= Q(media_type=MediaAsset.MediaType.VIDEO)
        elif target_type == 'image':
            filters &= Q(media_type=MediaAsset.MediaType.IMAGE)
        elif target_type == 'image_set':
            filters &= Q(media_type=MediaAsset.MediaType.IMAGE_SET)

        assets = MediaAsset.objects.filter(filters)
        self.stdout.write(f"Found {assets.count()} assets to process.")

        for asset in assets:
            try:
                self.process_asset(asset, force, dry_run)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed Asset {asset.id}: {e}"))

    def process_asset(self, asset, force, dry_run):
        # Resolve absolute path
        # Note: asset.file_path is relative to PROJECT_DIR
        abs_path = (settings.PROJECT_DIR / asset.file_path).resolve()
        
        if not abs_path.exists():
            self.stdout.write(self.style.WARNING(f"  [SKIP] ID {asset.id}: Source file not found at {abs_path}"))
            return

        thumb_rel_path = None

        # --- Dispatch based on Type ---
        if asset.media_type == MediaAsset.MediaType.VIDEO:
            thumb_rel_path = self.generate_video_thumb(asset, abs_path, dry_run)
        
        elif asset.media_type == MediaAsset.MediaType.IMAGE:
            thumb_rel_path = self.generate_image_thumb(asset, abs_path, dry_run)
            
        elif asset.media_type == MediaAsset.MediaType.IMAGE_SET:
            thumb_rel_path = self.generate_imageset_thumb(asset, abs_path, dry_run)

        # --- Save to DB ---
        if thumb_rel_path and not dry_run:
            asset.thumbnail_path = thumb_rel_path
            asset.save(update_fields=['thumbnail_path'])
            self.stdout.write(self.style.SUCCESS(f"  [OK] ID {asset.id}: Linked {thumb_rel_path}"))

    def generate_video_thumb(self, asset, video_path, dry_run):
        """Extracts a frame from the middle of the video."""
        # Naming: video.mp4 -> video_thumb.jpg
        thumb_name = f"{video_path.stem}_thumbnail.jpg"
        thumb_path = video_path.parent / thumb_name
        
        rel_path = str(thumb_path.relative_to(settings.PROJECT_DIR))

        if thumb_path.exists() and not dry_run:
            return rel_path

        if dry_run:
            self.stdout.write(f"  [DRY] Video Thumb: {rel_path}")
            return rel_path

        # Use OpenCV to grab a frame
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        # Jump to 50% of the video (usually better than 0% which might be black)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames * 0.5)
        
        ret, frame = cap.read()
        cap.release()

        if ret:
            # Resize while maintaining aspect ratio (max width 640)
            h, w = frame.shape[:2]
            scale = 640 / float(w)
            new_dim = (640, int(h * scale))
            resized = cv2.resize(frame, new_dim, interpolation=cv2.INTER_AREA)
            
            # Save as JPG
            cv2.imwrite(str(thumb_path), resized)
            return rel_path
        return None

    def generate_image_thumb(self, asset, image_path, dry_run):
        """Resizes a single image."""
        thumb_name = f"{image_path.stem}_thumb.jpg"
        thumb_path = image_path.parent / thumb_name
        rel_path = str(thumb_path.relative_to(settings.PROJECT_DIR))

        if dry_run:
            self.stdout.write(f"  [DRY] Image Thumb: {rel_path}")
            return rel_path

        self._create_thumb_from_image(image_path, thumb_path)
        return rel_path

    def generate_imageset_thumb(self, asset, folder_path, dry_run):
        """Finds the middle image in a set and creates a thumbnail."""
        thumb_name = "preview_thumbnail.jpg"
        thumb_path = folder_path / thumb_name
        
        # Calculate relative path for DB
        rel_path = str(thumb_path.relative_to(settings.PROJECT_DIR))

        if dry_run:
            self.stdout.write(f"  [DRY] ImageSet Thumb: {rel_path}")
            return rel_path

        # --- OPTIMIZATION START ---
        # Use os.scandir instead of Path.iterdir for 10x speedup on large folders
        valid_exts = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
        image_names = []

        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    # 'entry' is lightweight; entry.name is just a string
                    if entry.is_file() and "thumb" not in entry.name:
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in valid_exts:
                            image_names.append(entry.name)
        except OSError as e:
            self.stdout.write(self.style.ERROR(f"  [ERR] Could not scan {folder_path}: {e}"))
            return None
        # --- OPTIMIZATION END ---

        if not image_names:
            self.stdout.write(self.style.WARNING(f"  [SKIP] No images found in set {folder_path}"))
            return None

        # Sort strings (very fast)
        image_names.sort()

        # Pick middle image
        middle_idx = len(image_names) // 2
        source_image_name = image_names[middle_idx]
        
        # Only construct the full Path object for the ONE image we actually need
        source_image_path = folder_path / source_image_name

        self._create_thumb_from_image(source_image_path, thumb_path)
        return rel_path

    def _create_thumb_from_image(self, source_path, dest_path):
        """Helper to resize and save using Pillow."""
        try:
            with Image.open(source_path) as img:
                # Convert to RGB (fixes issues with PNG transparency or Tiff)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Create thumbnail (in-place resize)
                img.thumbnail((640, 480)) 
                img.save(dest_path, "JPEG", quality=85)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating thumb from {source_path}: {e}"))
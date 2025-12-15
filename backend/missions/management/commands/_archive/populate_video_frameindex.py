import os
from pathlib import Path
from django.conf import settings
from datetime import datetime, timezone, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as django_timezone
from django.db import transaction
from missions.models import MediaAsset, FrameIndex, NavSample
from bisect import bisect_left
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Populate FrameIndex for a video MediaAsset by calculating frame timestamps and linking closest NavSample."

    def add_arguments(self, parser):
        # Create a group so user must pick either --mediaasset-id OR --all
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--mediaasset-id", 
            type=int, 
            help="ID of the specific MediaAsset to process."
        )
        group.add_argument(
            "--all", 
            action="store_true", 
            help="Process ALL valid video MediaAssets."
        )

        parser.add_argument(
            "--batch-size", 
            type=int, 
            default=1000, 
            help="Batch size for bulk insert operations."
        )
        parser.add_argument(
            "--force", 
            action="store_true", 
            help="Force re-processing even if FrameIndex records already exist."
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        force = options["force"]
        
        # 1. Determine which assets to process
        if options["all"]:
            # Filter for videos that have the necessary metadata
            assets = MediaAsset.objects.filter(
                media_type=MediaAsset.MediaType.VIDEO,
                start_time__isnull=False,
                end_time__isnull=False,
                fps__isnull=False
            )
            self.stdout.write(f"Found {assets.count()} total video assets.")
        else:
            # Fetch single asset
            try:
                asset = MediaAsset.objects.get(pk=options["mediaasset_id"])
                # Validate it's a video
                if asset.media_type != MediaAsset.MediaType.VIDEO:
                    raise CommandError(f"MediaAsset {asset.id} is not a video.")
                if not (asset.start_time and asset.end_time and asset.fps):
                    raise CommandError(f"MediaAsset {asset.id} missing start_time, end_time, or fps.")
                assets = [asset]
            except MediaAsset.DoesNotExist:
                raise CommandError(f"MediaAsset with id={options['mediaasset_id']} does not exist.")

        # 2. Iterate and process
        success_count = 0
        skip_count = 0
        fail_count = 0

        for media_asset in assets:
            try:
                # Check if already processed (skip unless forced)
                if not force and FrameIndex.objects.filter(media_asset=media_asset).exists():
                    self.stdout.write(f"Skipping {media_asset} (ID: {media_asset.id}) - Already processed.")
                    skip_count += 1
                    continue

                self.stdout.write(f"Processing {media_asset} (ID: {media_asset.id})...")
                
                # Get mission from the deployment linked to the asset
                mission = media_asset.deployment.mission
                
                # Initialize processor (using your existing class)
                processor = FrameIndexProcessor(
                    media_asset=media_asset,
                    mission=mission,
                    batch_size=batch_size,
                    force=force,
                    stdout=self.stdout
                )
                
                # Run the processing
                processor.run()
                success_count += 1
                
            except Exception as e:
                # Catch errors per video so the whole batch doesn't fail
                self.stdout.write(self.style.ERROR(f"Failed to process MediaAsset {media_asset.id}: {e}"))
                logger.exception(f"Error processing MediaAsset {media_asset.id}")
                fail_count += 1

        # 3. Final Summary
        self.stdout.write(self.style.SUCCESS("------------------------------------------------"))
        self.stdout.write(self.style.SUCCESS(f"Batch Processing Complete."))
        self.stdout.write(f"  Successfully processed: {success_count}")
        self.stdout.write(f"  Skipped (already done): {skip_count}")
        self.stdout.write(f"  Failed:                 {fail_count}")


class FrameIndexProcessor:
    """
    Processor class for populating FrameIndex from MediaAsset video metadata.
    
    This class handles the calculation of frame timestamps and linking to the closest
    NavSample records for a given mission.
    """
    
    def __init__(self, media_asset, mission, batch_size=1000, force=False, stdout=None):
        self.media_asset = media_asset
        self.mission = mission
        self.batch_size = batch_size
        self.force = force
        self.stdout = stdout
        
        self.stats = {
            "total_frames": 0,
            "frames_with_nav": 0,
            "frames_without_nav": 0,
            "errors": 0,
            "nav_samples_loaded": 0,
            "avg_time_diff_ms": 0.0,
            "max_time_diff_ms": 0.0,
        }
    
    def log_message(self, message):
        """Helper to log messages to stdout if available."""
        if self.stdout:
            self.stdout.write(message)
    
    def run(self):
        """Main processing loop."""
        self.log_message("Starting frame index population...")
        
        # Clear existing frame indexes if force is enabled
        if self.force:
            deleted_count = FrameIndex.objects.filter(media_asset=self.media_asset).count()
            if deleted_count > 0:
                FrameIndex.objects.filter(media_asset=self.media_asset).delete()
                self.log_message(f"Deleted {deleted_count} existing frame indexes")
        
        # Load nav samples for the mission
        nav_samples = self._load_nav_samples()
        
        # Calculate frame parameters
        fps = float(self.media_asset.fps)
        frame_interval = timedelta(seconds=1 / fps)
        duration_seconds = (self.media_asset.end_time - self.media_asset.start_time).total_seconds()
        total_frames = int(duration_seconds * fps)
        
        self.log_message(f"Calculated {total_frames} frames at {fps} FPS")
        self.log_message(f"Frame interval: {frame_interval}")
        self.log_message(f"Loaded {len(nav_samples)} nav samples for mission")
        
        self.stats["total_frames"] = total_frames
        self.stats["nav_samples_loaded"] = len(nav_samples)
        
        # Process frames in batches
        batch = []
        time_diffs = []
        
        for frame_number in range(total_frames):
            try:
                # Calculate frame timestamp
                timestamp = self.media_asset.start_time + frame_number * frame_interval
                
                # Find closest nav sample
                closest_nav_id, time_diff_ms = self._find_closest_nav_sample(
                    timestamp, nav_samples
                )
                
                # Track timing statistics
                if time_diff_ms is not None:
                    time_diffs.append(time_diff_ms)
                    self.stats["frames_with_nav"] += 1
                    if time_diff_ms > self.stats["max_time_diff_ms"]:
                        self.stats["max_time_diff_ms"] = time_diff_ms
                else:
                    self.stats["frames_without_nav"] += 1
                
                # Create frame index object
                frame_index = FrameIndex(
                    media_asset=self.media_asset,
                    frame_number=frame_number,
                    timestamp=timestamp,
                    closest_nav_sample_id=closest_nav_id,
                    nav_match_time_diff_ms=time_diff_ms,
                )
                
                batch.append(frame_index)
                
                # Flush batch if it reaches the batch size
                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch = []
                    
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Error processing frame {frame_number}: {str(e)}")
                continue
        
        # Flush any remaining frames
        if batch:
            self._flush_batch(batch)
        
        # Calculate average time difference
        if time_diffs:
            self.stats["avg_time_diff_ms"] = sum(time_diffs) / len(time_diffs)
        
        # Print final statistics
        self._print_statistics()
    
    def _load_nav_samples(self):
        """Load all nav samples for the mission, sorted by timestamp."""
        nav_samples = list(
            NavSample.objects.filter(mission=self.mission)
            .order_by('timestamp')
            .values('id', 'timestamp')
        )
        
        if not nav_samples:
            self.log_message("WARNING: No nav samples found for mission")
        
        return nav_samples
    
    def _find_closest_nav_sample(self, target_timestamp, nav_samples):
        """
        Find the closest nav sample to the target timestamp using binary search.
        
        Returns:
            tuple: (nav_sample_id, time_diff_ms) or (None, None) if no samples
        """
        if not nav_samples:
            return None, None
        
        # Extract timestamps for binary search
        timestamps = [ns['timestamp'] for ns in nav_samples]
        
        # Find insertion point
        pos = bisect_left(timestamps, target_timestamp)
        
        # Handle edge cases
        if pos == 0:
            # Target is before all samples
            closest_sample = nav_samples[0]
        elif pos == len(timestamps):
            # Target is after all samples
            closest_sample = nav_samples[-1]
        else:
            # Target is between samples, find the closer one
            before_sample = nav_samples[pos - 1]
            after_sample = nav_samples[pos]
            
            before_diff = abs((target_timestamp - before_sample['timestamp']).total_seconds())
            after_diff = abs((after_sample['timestamp'] - target_timestamp).total_seconds())
            
            if before_diff <= after_diff:
                closest_sample = before_sample
            else:
                closest_sample = after_sample
        
        # Calculate time difference in milliseconds
        time_diff = (target_timestamp - closest_sample['timestamp']).total_seconds() * 1000
        time_diff_ms = int(abs(time_diff))
        
        return closest_sample['id'], time_diff_ms
    
    def _flush_batch(self, batch):
        """Flush a batch of frame indexes to the database."""
        if not batch:
            return
        
        try:
            with transaction.atomic():
                FrameIndex.objects.bulk_create(batch, ignore_conflicts=True)
            self.log_message(f"Saved {len(batch)} frame indexes")
        except Exception as e:
            logger.error(f"Error saving frame index batch: {str(e)}")
            self.stats["errors"] += len(batch)
    
    def _print_statistics(self):
        """Print processing statistics."""
        self.log_message(f"\nFrame index population complete! Statistics:")
        self.log_message(f"  Total frames: {self.stats['total_frames']}")
        self.log_message(f"  Frames with nav data: {self.stats['frames_with_nav']}")
        self.log_message(f"  Frames without nav data: {self.stats['frames_without_nav']}")
        self.log_message(f"  Errors: {self.stats['errors']}")
        self.log_message(f"  Nav samples loaded: {self.stats['nav_samples_loaded']}")
        
        if self.stats['frames_with_nav'] > 0:
            self.log_message(f"  Average time difference: {self.stats['avg_time_diff_ms']:.1f}ms")
            self.log_message(f"  Maximum time difference: {self.stats['max_time_diff_ms']}ms")
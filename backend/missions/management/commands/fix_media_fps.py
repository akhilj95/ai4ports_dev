from django.core.management.base import BaseCommand
from missions.models import MediaAsset
from django.db.models import Q

class Command(BaseCommand):
    help = 'Calculates and fixes FPS metadata for video assets based on actual frame counts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run analysis without saving changes to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.stdout.write(f"Starting FPS verification... (Dry Run: {dry_run})")

        assets = MediaAsset.objects.filter(
            Q(media_type=MediaAsset.MediaType.VIDEO) | 
            Q(media_type=MediaAsset.MediaType.IMAGE_SET)
        ).iterator()

        updated_count = 0
        crashed_count = 0
        skipped_count = 0

        for asset in assets:
            if not asset.start_time or not asset.end_time:
                continue

            duration = (asset.end_time - asset.start_time).total_seconds()
            if duration <= 0:
                continue

            frame_count = asset.frames.count()
            if frame_count == 0:
                continue

            # Calculate the "Real" FPS
            calc_fps = frame_count / duration
            
            # Current stored FPS (default to 0 if None)
            stored_fps = float(asset.fps) if asset.fps else 0.0

            # --- DIAGNOSIS LOGIC ---

            # CASE 1: Likely Crashed / Incomplete Indexing
            # If FPS is suspiciously low (< 5), the indexing job probably died.
            if calc_fps < 5.0:
                self.stdout.write(self.style.ERROR(
                    f"❌ Asset {asset.id}: CRITICAL - FPS is {calc_fps:.2f} (Duration: {duration}s, Frames: {frame_count}). "
                    f"This asset likely needs re-indexing."
                ))
                crashed_count += 1
                continue

            # CASE 2: FPS Mismatch (e.g. Database says None/25, Reality is 16.6)
            # We verify if the difference is significant (> 0.5 difference)
            if abs(stored_fps - calc_fps) > 0.5:
                # Round to reasonable precision (e.g. 16.6666 -> 16.667)
                new_fps = round(calc_fps, 3)
                
                msg = f"Asset {asset.id}: Updating FPS {stored_fps} -> {new_fps} (Duration: {duration:.1f}s)"
                
                if dry_run:
                    self.stdout.write(self.style.WARNING(f"[DRY RUN] {msg}"))
                else:
                    asset.fps = new_fps
                    asset.save(update_fields=['fps'])
                    self.stdout.write(self.style.SUCCESS(f"✅ {msg}"))
                    updated_count += 1
            else:
                skipped_count += 1

        # Summary
        self.stdout.write("\n" + "-"*30)
        self.stdout.write(f"Finished processing.")
        self.stdout.write(f"Updated: {updated_count}")
        self.stdout.write(f"Skipped (Already Correct): {skipped_count}")
        self.stdout.write(self.style.ERROR(f"Crashed/Broken Assets: {crashed_count}"))
        
        if dry_run:
            self.stdout.write(self.style.WARNING("No changes were made to the database."))
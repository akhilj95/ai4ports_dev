import math
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db.models import F
from missions.models import Mission, NavSample, TideLevel, MediaAsset

class Command(BaseCommand):
    help = "Calculates hydrographic depth correction using Harmonic Analysis formulas."

    def add_arguments(self, parser):
        parser.add_argument(
            '--mission-id', 
            type=int, 
            help='Specific Mission ID to process.'
        )
        parser.add_argument(
            '--port-name',
            type=str,
            default='ponta_delgada',
            choices=['ponta_delgada', 'horta'],
            help='The port to use for tide reference.'
        )

    def handle(self, *args, **options):
        mission_id = options['mission_id']
        port_name = options['port_name']

        # 1. Filter Missions
        missions = Mission.objects.all()
        if mission_id:
            missions = missions.filter(pk=mission_id)

        self.stdout.write(f"Processing {missions.count()} missions using tide data for {port_name}...")

        total_updated = 0
        
        for mission in missions:
            self.stdout.write(f"--> Processing Mission {mission.id}...")
            
            # Fetch all samples for this mission, ordered by time
            samples = list(NavSample.objects.filter(mission=mission).order_by('timestamp'))
            
            if not samples:
                continue

            # Optimize Tide Loading: Get tides overlapping the mission duration (with 7h buffer)
            start_time = samples[0].timestamp - timedelta(hours=7)
            end_time = samples[-1].timestamp + timedelta(hours=7)
            
            tide_events = list(TideLevel.objects.filter(
                port_name=port_name,
                time__range=(start_time, end_time)
            ).order_by('time'))

            if not tide_events:
                self.stdout.write(self.style.WARNING(f"   No tide data found for Mission {mission.id} range."))
                continue

            samples_to_update = []

            # Iterate through samples and correct depth
            for sample in samples:
                if sample.depth_m is None:
                    continue

                # Find surrounding tide events
                prev_event, next_event = self.get_surrounding_tides(sample.timestamp, tide_events)

                if prev_event and next_event:
                    # Calculate Tide Height (y) using the unified formula
                    tide_height = self.calculate_tide_height(sample.timestamp, prev_event, next_event)
                    
                    # Apply Correction: 
                    # Corrected Depth = Measured Depth - Tide Height 
                    # (Assuming positive tide increases sensor reading, so we subtract to normalize to Chart Datum)
                    sample.corrected_depth_m = sample.depth_m - tide_height
                    samples_to_update.append(sample)
            
            # Perform Bulk Update for speed
            if samples_to_update:
                NavSample.objects.bulk_update(samples_to_update, ['corrected_depth_m'], batch_size=1000)
                total_updated += len(samples_to_update)
                self.stdout.write(f"   Updated {len(samples_to_update)} samples.")

                self.stdout.write("   Recalculating statistics for affected MediaAssets...")
                # Find all assets linked to this mission via their deployment
                assets = MediaAsset.objects.filter(deployment__mission=mission)
                
                count = 0
                for asset in assets:
                    asset.calculate_stats() # Recalculates using the new corrected depths
                    count += 1
                
                self.stdout.write(f"   Updated stats for {count} assets.")
        
        self.stdout.write(self.style.SUCCESS(f"Finished. Successfully corrected {total_updated} NavSamples."))

    def get_surrounding_tides(self, sample_time, tide_events):
        """
        Finds the tide event immediately before and immediately after the sample time.
        """
        # Since tide_events is sorted, we iterate to find the interval
        for i in range(len(tide_events) - 1):
            if tide_events[i].time <= sample_time <= tide_events[i+1].time:
                return tide_events[i], tide_events[i+1]
        
        return None, None

    def calculate_tide_height(self, current_time, prev_event, next_event):
        """
        Calculates tide height (y) at a specific instant (t) using the cosine interpolation method.
        
        Formula derived from Instituto Hidrográfico:
        y = (H_start + H_end)/2 + (H_start - H_end)/2 * cos(pi * t / T)
        
        This works mathematically for both:
        - Falling Tide (a): H_start > H_end
        - Rising Tide (b): H_start < H_end
        """
        # T: Total duration between events in seconds
        T_seconds = (next_event.time - prev_event.time).total_seconds()
        if T_seconds == 0: return prev_event.tide_height_m

        # t: Time elapsed since previous event
        t_seconds = (current_time - prev_event.time).total_seconds()

        # Tide Heights
        H_start = prev_event.tide_height_m
        H_end   = next_event.tide_height_m

        # Unified Formula
        term1 = (H_start + H_end) / 2
        term2 = (H_start - H_end) / 2
        term3 = math.cos((math.pi * t_seconds) / T_seconds)
        
        y = term1 + (term2 * term3)
        return y
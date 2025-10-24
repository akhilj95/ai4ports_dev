from django.db import models
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
import logging

# Get a logger instance
logger = logging.getLogger(__name__)

#  ------------------------------------------------------------------
#  1. Hardware options
#  ------------------------------------------------------------------

class RoverHardware(models.Model):
    """
    Represents the hardware configuration versioning for a rover
    Only one active configuration per rover name is allowed at a time.
    """
    name = models.CharField(max_length=100)
    
    # versioning / config
    effective_from  = models.DateTimeField(default=timezone.now)
    hardware_config = models.JSONField(default=dict, blank=True)
    active          = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(active=True),
                name="unique_active_roverhardware_per_name",
            )
        ]
        ordering = ["-effective_from"]

    def save(self, *args, **kwargs):
        # Ensure that, per rover `name`, only one row remains `active=True`.
        try:
            with transaction.atomic():
                # Wrap in a transaction so “unset olds” + “save new” is atomic
                if self.active:
                    (RoverHardware.objects
                        .filter(name=self.name, active=True)
                        .exclude(pk=self.pk)                  # skip self on update
                        .update(active=False))
                super().save(*args, **kwargs)
        except Exception as e:
            logger.error(f"Failed to save RoverHardware {self.name}: {e}")
            raise

    def __str__(self):
        status = "Active" if self.active else "Inactive"
        return f"{self.name} ({self.effective_from:%Y-%m-%d}) - {status}"
    

#  ------------------------------------------------------------------
#  2. Sensors and calibrations
#  ------------------------------------------------------------------
    
class Sensor(models.Model):
    """
    Represents a sensor that can be deployed on a rover.
    Each sensor has a type, name, and optional specification.
    """
    class SensorType(models.TextChoices):
        CAMERA = "camera", "Camera"
        COMPASS = "compass", "Compass"
        IMU = "imu", "IMU"
        PRESSURE = "pressure", "Pressure"
        SONAR = "sonar", "Sonar"
        WATER_QUALITY = "water_quality", "Water Quality"

    sensor_type     = models.CharField(max_length=20, choices=SensorType.choices)
    name            = models.CharField(max_length=100, unique=True)
    specification   = models.JSONField(blank=True, default=dict)

    def __str__(self):
        return self.name


class Calibration(models.Model):
    """
    Optional per-sensor (not per-mission) calibration history.
    Each sensor has calibration coefficients in JSON format.
    Only one calibration can be active at a time for a sensor.
    """
    sensor          = models.ForeignKey(
        Sensor,
        on_delete=models.PROTECT,
        related_name="calibrations"
    )
    effective_from  = models.DateTimeField(default=timezone.now)
    coefficients    = models.JSONField(blank=True, default=dict)
    active          = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sensor"],
                condition=models.Q(active=True),
                name="one_active_calibration_per_sensor",
            ),
        ]
        ordering = ["-effective_from"]

    def save(self, *args, **kwargs):
        # Wrap in a transaction so “unset olds” + “save new” is atomic
        with transaction.atomic():
            if self.active:
                (Calibration.objects
                   .filter(sensor=self.sensor, active=True)
                   .exclude(pk=self.pk)           # skip self on update
                   .update(active=False))
            super().save(*args, **kwargs)

    def __str__(self):
        status = "Active" if self.active else "Inactive"
        return f"{self.sensor} since {self.effective_from:%Y-%m-%d} - {status}"


#  ------------------------------------------------------------------
#  3. Mission and mission specific deployments
#  ------------------------------------------------------------------

class Mission(models.Model):
    """
    Represents a mission that inspects a single target.
    """
    class TargetType(models.TextChoices):
        PILLAR = "pillar", "Pillar"
        WALL   = "wall",   "Wall"

    class LevelChoices(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    rover        = models.ForeignKey(
        RoverHardware, on_delete=models.PROTECT, related_name="missions"
    )
    start_time   = models.DateTimeField(default=timezone.now)
    end_time     = models.DateTimeField(null=True, blank=True)
    location     = models.CharField(max_length=50, blank=True)

    # Approx gps
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    target_type  = models.CharField(
        max_length=12,                     # safety margin of 6
        choices=TargetType.choices,
        default=TargetType.WALL,
    )    

    max_depth    = models.FloatField(null=True, blank=True)
    visibility   = models.CharField(
        max_length=6,
        choices=LevelChoices.choices,
        default=LevelChoices.MEDIUM,
        blank=True,
        help_text="Visibility quality: low, medium, or high"
    )
    driving_difficulty = models.CharField(
        max_length=6,
        choices=LevelChoices.choices,
        default=LevelChoices.MEDIUM,
        blank=True,
        help_text="Driving difficulty: low, medium, or high"
    )
    
    notes  = models.TextField(blank=True)

    def clean(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time")
    
    class Meta:
        indexes = [models.Index(fields=["start_time"])]
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.rover.name} - {self.location} @ {self.start_time:%Y-%m-%d %H:%M}"

class SensorDeployment(models.Model):
    """
    Represents the specific deployment characteristics of a sensor on
    a specific mission.
    """
    mission     = models.ForeignKey(Mission, on_delete=models.CASCADE,
                                    related_name="deployments")
    sensor      = models.ForeignKey(Sensor, on_delete=models.PROTECT,
                                    related_name="deployments")
    calibration = models.ForeignKey(Calibration, on_delete=models.PROTECT,
                                    null=True, blank=True)
    position    = models.CharField(max_length=50)   # e.g. “bow-port”

    INSTANCE_CHOICES = [
        (0, '0'),
        (1, '1'),
    ]
    # Instance number for sensors types that can have multiple instances (e.g. Compass or Camera)
    # 0 for primary, 1 for secondary (if applicable)
    instance = models.IntegerField(
        choices=INSTANCE_CHOICES,
        default=0,
        help_text="Sensor type instance number (0 or 1 only)."
    )

    def clean(self):
        super().clean()  # Call the parent clean method first
        if self.calibration and self.calibration.sensor != self.sensor:
            raise ValidationError(
                "The calibration must belong to the same sensor as the deployment."
            )

    class Meta:
        indexes = [
            models.Index(fields=["mission"]),
            models.Index(fields=["sensor"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["mission", "sensor", "instance"],
                name="unique_sensor_instance_per_mission"
            )
        ]

    # making sure validation is done before saving
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.sensor} on {self.mission} ({self.position})"

#  ------------------------------------------------------------------
#  4. Log files
#  ------------------------------------------------------------------
class LogFile(models.Model):
    """
    Represents the log files generated. The .bin file is the dataflash log,
    that's captured on the rover at a high framerate. The .tlog file is 
    the telemetry log that is generated by the ground station.
    Paths to files are stored as strings, assuming external file management.
    """
    mission = models.ForeignKey(
        Mission,
        on_delete=models.CASCADE,
        related_name="log_files"
    )
    bin_path = models.CharField(
        max_length=500,
        null=True,
        blank=True
    )
    tlog_path = models.CharField(
        max_length=500,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    already_parsed = models.BooleanField(default=False)

    def clean(self):
        if not self.bin_path and not self.tlog_path:
            raise ValidationError("At least one of bin_path or tlog_path must be provided.")

    class Meta:
        indexes = [
            models.Index(fields=["mission"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    # making sure validation is done before saving
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        files = []
        if self.bin_path:
            files.append(".bin")
        if self.tlog_path:
            files.append(".tlog")
        return f"Log for {self.mission} ({', '.join(files)} at {self.created_at:%Y-%m-%d %H:%M})"
    

#  ------------------------------------------------------------------
#  5. Navigation readings
#  ------------------------------------------------------------------
class NavSample(models.Model):
    """Subset of EKF state needed for media filtering."""
    mission   = models.ForeignKey(Mission, on_delete=models.CASCADE,
                                  related_name="nav_samples")
    timestamp = models.DateTimeField()

    # depth is often logged; altitude above seabed may be derived
    depth_m     = models.FloatField(null=True, blank=True)

    roll_deg    = models.FloatField(null=True, blank=True)
    pitch_deg   = models.FloatField(null=True, blank=True)
    yaw_deg     = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["mission", "timestamp"]),
            models.Index(fields=["depth_m"]),
            models.Index(fields=["depth_m","yaw_deg"]),
        ]
        ordering = ["mission", "timestamp"]

#  ------------------------------------------------------------------
#  6. Video and image data
#  ------------------------------------------------------------------
class MediaAsset(models.Model):
    """
    Represents a raw media file generated during a mission. Media can be images or videos.
    It could be data from one of the cameras or the imaging sonar.
    Paths to files are stored as strings, assuming external file management.
    """
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    deployment   = models.ForeignKey(
        SensorDeployment, on_delete=models.PROTECT, related_name="media")
    media_type   = models.CharField(max_length=6, choices=MediaType.choices)
    file_path    = models.CharField(max_length=500)
    start_time   = models.DateTimeField()        # UTC
    end_time     = models.DateTimeField(null=True, blank=True)   # video only
    fps          = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)      # video only
    file_metadata = models.JSONField(default=dict, blank=True)
    notes        = models.TextField(blank=True)

    def clean(self):
        # Ensure file_path is not empty
        if not self.file_path.strip():
            raise ValidationError("File path cannot be empty")
        # Making sure start_time is timezone-aware
        if not timezone.is_aware(self.start_time):
            raise ValidationError("Start time must be timezone-aware.")
        # Images: no end_time / fps allowed
        if self.media_type == self.MediaType.IMAGE:
            if self.end_time or self.fps:
                raise ValidationError("Images must not have end_time or fps")
        # Videos: ensure end_time > start_time
        if self.media_type == self.MediaType.VIDEO:
            if not self.end_time:
                raise ValidationError("Videos require end_time")
            if self.end_time <= self.start_time:
                raise ValidationError("end_time must be after start_time")
            if self.end_time and not timezone.is_aware(self.end_time):
                raise ValidationError("End time must be timezone-aware.")

    class Meta:
        indexes = [models.Index(fields=["start_time"])]
        ordering = ["start_time"]


class FrameIndex(models.Model):
    """
    Represents a frame in a media asset, which could be an image or a video.
    Each frame is linked to a media asset and optionally to a navigation sample.
    It contains metadata about the frame, such as its number, timestamp, and servo pitch.
    This allows for detailed indexing of frames within a media asset.
    It could be data from one of the cameras or the imaging sonar.
    """
    media_asset   = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name="frames")
    frame_number  = models.PositiveIntegerField(null=True, blank=True)
    timestamp     = models.DateTimeField()
    servo_pitch_deg = models.FloatField(null=True, blank=True)   # for Rpi camera tilt

    # link to navigation
    # optional to allow flexible processing workflow
    closest_nav_sample    = models.ForeignKey(
        NavSample, on_delete=models.PROTECT, related_name="frames",
        null=True, blank=True)
    # Track matching quality
    nav_match_time_diff_ms = models.IntegerField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.timestamp and not timezone.is_aware(self.timestamp):
            raise ValidationError("Timestamp must be timezone-aware.")
        # frame timestamps must lie inside the clip boundaries
        if self.timestamp < self.media_asset.start_time:
            raise ValidationError("Frame timestamp before video/image start_time")
        if (
            self.media_asset.media_type == MediaAsset.MediaType.VIDEO
            and self.media_asset.end_time
            and self.timestamp > self.media_asset.end_time
        ):
            raise ValidationError("Frame timestamp after video end_time")

    class Meta:
        indexes = [
            models.Index(fields=["timestamp"]),
        ]
        ordering = ["media_asset", "frame_number"]

#  ------------------------------------------------------------------
#  7. Sonar data
#  ------------------------------------------------------------------
# For sonar data as text files, to be implemented later.

#  ------------------------------------------------------------------
#  8. Other sensor readings
#  ------------------------------------------------------------------

# common base (abstract; no DB table)
class SensorSampleBase(models.Model):
    """
    Columns common to every raw sensor sample extracted from a .bin/.tlog file.
    One row = one sample at one instant in one logfile.
    """
    log_file   = models.ForeignKey(
        LogFile, on_delete=models.CASCADE, related_name="%(class)s"
    )
    deployment = models.ForeignKey(           # which physical sensor produced it
        SensorDeployment, on_delete=models.CASCADE, related_name="%(class)s"
    )
    # UTC time stamp – fill this once you've converted the log-relative time
    timestamp  = models.DateTimeField()

    class Meta:
        abstract = True
        ordering = ["timestamp"]
        indexes  = [
            models.Index(fields=["deployment", "timestamp"]),
        ]

    # Make sure the row is linked to the correct sensor *type*
    EXPECTED_SENSOR_TYPE: str = ""      # to be overloaded below

    def clean(self):
        super().clean()
        if (
            self.EXPECTED_SENSOR_TYPE
            and self.deployment.sensor.sensor_type != self.EXPECTED_SENSOR_TYPE
        ):
            raise ValidationError(
                f"Deployment must be of type "
                f"'{self.EXPECTED_SENSOR_TYPE}' (got "
                f"'{self.deployment.sensor.sensor_type}')"
            )
        if self.timestamp and not timezone.is_aware(self.timestamp):
            raise ValidationError("Timestamp must be timezone-aware (UTC).")

    def __str__(self):
        return f"{self.deployment} @ {self.timestamp:%H:%M:%S.%f}"
    
class ImuSample(SensorSampleBase):
    """6-DOF IMU: angular rate (rad s⁻¹) + specific force (m s⁻²)."""
    gx_rad_s = models.FloatField()
    gy_rad_s = models.FloatField()
    gz_rad_s = models.FloatField()
    ax_m_s2  = models.FloatField()
    ay_m_s2  = models.FloatField()
    az_m_s2  = models.FloatField()

    EXPECTED_SENSOR_TYPE = Sensor.SensorType.IMU


class CompassSample(SensorSampleBase):
    """3-axis magnetic field in µT (works for both onboard magnetometers)."""
    mx_uT = models.FloatField()
    my_uT = models.FloatField()
    mz_uT = models.FloatField()

    EXPECTED_SENSOR_TYPE = Sensor.SensorType.COMPASS


class PressureSample(SensorSampleBase):
    """Absolute pressure plus optional temperature (use Pa to keep units SI)."""
    pressure_pa   = models.FloatField()
    temperature_C = models.FloatField(null=True, blank=True)

    EXPECTED_SENSOR_TYPE = Sensor.SensorType.PRESSURE

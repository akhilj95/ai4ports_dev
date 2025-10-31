from rest_framework import serializers
from . import models

# Serializer for RoverHardware model
class RoverHardwareSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RoverHardware
        fields = ("id", "name", "effective_from", "hardware_config", "active")
        # Adding active to read only since I want to ensure it is not modified directly
        # Neeeds to be re check the logic in models and viewset
        read_only_fields = ("id", "active")


# Serializer for Calibration model
class CalibrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Calibration
        fields = ("id", "effective_from", "coefficients", "active")
        # Adding active to read only since I want to ensure it is not modified directly
        # Neeeds to be re check the logic in models and viewset
        read_only_fields = ("id", "active")


# Serializer for Sensor model, includes a nested active calibration
class SensorSerializer(serializers.ModelSerializer):
    active_calibration = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Sensor
        fields = ("id", "name", "sensor_type", "specification", "active_calibration")
        read_only_fields = ("id",)

    # Method to fetch the active calibration associated with the sensor
    def get_active_calibration(self, obj):
        # Try to use prefetched calibrations if available
        active = getattr(obj, "_prefetched_objects_cache", {}).get("calibrations")
        if active is None:
            # If not prefetched, fetch active calibrations from DB
            active = obj.calibrations.filter(active=True)
        calib = active.first()
        return CalibrationSerializer(calib).data if calib else None


# Serializer for Mission model with validation for time and depth fields
class MissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Mission
        fields = (
            "id",
            "rover",
            "start_time",
            "end_time",
            "location",
            "target_type",
            "max_depth",
            "visibility",
            "driving_difficulty",
            "notes",
        )

    # Validate object-level constraints: end_time must be after start_time
    def validate(self, attrs):
        # Use current instance values if not provided in new data, mainly for updates
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        return attrs

    # Validate 'max_depth' field to ensure it is positive if provided
    def validate_max_depth(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Depth must be positive in metres.")
        return value

# Serializer for SensorDeployment model
# adding custom fields for latest calibration coefficients and sensor name
class SensorDeploymentSerializer(serializers.ModelSerializer):
    # Custom field to retrieve latest calibration coefficients (active or specified
    latest_coefficients = serializers.SerializerMethodField(read_only=True)
    # Expose linked sensor's name as a read-only field
    sensor_name = serializers.CharField(source="sensor.name", read_only=True)
    # Allows choosing instance number for the deployment, default 0
    instance = serializers.ChoiceField(choices=[(0, '0'), (1, '1')], default=0)

    class Meta:
        model = models.SensorDeployment
        fields = (
            "id",
            "mission",
            "sensor",
            "sensor_name",
            "position",
            "calibration",
            "latest_coefficients",
            "instance",
        )

    # Method to get latest coefficients 
    # either specified calibration or active calibration from sensor
    def get_latest_coefficients(self, obj):
        calib = obj.calibration or obj.sensor.calibrations.filter(active=True).first()
        return calib.coefficients if calib else None


# Serializer for LogFile model with validation ensuring at least one log path is provided
class LogFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.LogFile
        fields = (
            "id",
            "mission",
            "bin_path",
            "tlog_path",
            "created_at",
            "notes",
        )

    def validate(self, attrs):
        bin_path = attrs.get("bin_path") or getattr(self.instance, "bin_path", None)
        tlog_path = attrs.get("tlog_path") or getattr(self.instance, "tlog_path", None)
        if not bin_path and not tlog_path:
            raise serializers.ValidationError(
                "At least one of bin_path or tlog_path must be provided."
            )
        return attrs


# Serializer for NavSample model representing navigation data points
class NavSampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.NavSample
        fields = ('id', 'mission', 'timestamp', 'depth_m', 'roll_deg', 'pitch_deg', 'yaw_deg')
        read_only_fields = ('id',)


# Base serializer for simple sensor samples - used as the parent for specific sample types
class _BaseSampleSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ("id", "deployment", "timestamp")
        read_only_fields = ("id",)

# Serializer for IMU sensor samples with gyroscope and accelerometer data
class ImuSampleSerializer(_BaseSampleSerializer):
    class Meta(_BaseSampleSerializer.Meta):
        model = models.ImuSample
        # Add IMU-specific fields to base fields
        fields = _BaseSampleSerializer.Meta.fields + (
            "gx_rad_s",
            "gy_rad_s",
            "gz_rad_s",
            "ax_m_s2",
            "ay_m_s2",
            "az_m_s2",
        )

# Serializer for compass sensor samples with magnetic field strength data
class CompassSampleSerializer(_BaseSampleSerializer):
    class Meta(_BaseSampleSerializer.Meta):
        model = models.CompassSample
        # Add compass-specific magnetic field components
        fields = _BaseSampleSerializer.Meta.fields + (
            "mx_uT",
            "my_uT",
            "mz_uT",
        )

# Serializer for pressure sensor samples with pressure and temperature data
class PressureSampleSerializer(_BaseSampleSerializer):
    class Meta(_BaseSampleSerializer.Meta):
        model = models.PressureSample
        # Add pressure and temperature fields
        fields = _BaseSampleSerializer.Meta.fields + (
            "pressure_pa",
            "temperature_C",
        )

# Serializer for MediaAsset model - e.g., images or videos collected during missions
class MediaAssetSerializer(serializers.ModelSerializer):
    # Custom field to include deployment details
    deployment_details = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = models.MediaAsset
        fields = (
            'id', 'deployment', 'media_type', 'file_path', 'start_time', 
            'end_time', 'fps', 'file_metadata', 'notes', 'deployment_details',
        )
        read_only_fields = ('id',)
    
    # Provide dictionary with deployment and mission info for the media asset
    def get_deployment_details(self, obj):
        return {
            'sensor_name': obj.deployment.sensor.name,
            'sensor_type': obj.deployment.sensor.sensor_type,
            'mission_id': obj.deployment.mission.id,
            'mission_location': obj.deployment.mission.location
        }
    
    # Call validation from the parent class
    def validate(self, attrs):
        instance = models.MediaAsset(**attrs)
        instance.clean()
        return attrs

# Serializer for FrameIndex model linking frames of media to navigation samples
class FrameIndexSerializer(serializers.ModelSerializer):
    # Expose the file path of the related media asset as a read-only field
    media_asset_path = serializers.CharField(source='media_asset.file_path', read_only=True)
    # Include details of the closest navigation sample if it exists
    nav_sample_details = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.FrameIndex
        fields = (
            'id', 'media_asset', 'frame_number', 'timestamp', 'servo_pitch_deg',
            'closest_nav_sample', 'nav_match_time_diff_ms', 'media_asset_path',
            'nav_sample_details'
        )
        read_only_fields = ('id',)
    
    # Method to create a dict of relevant navigation parameters from closest nav sample
    def get_nav_sample_details(self, obj):
        if obj.closest_nav_sample:
            return {
                'depth_m': obj.closest_nav_sample.depth_m,
                'yaw_deg': obj.closest_nav_sample.yaw_deg,
                'pitch_deg': obj.closest_nav_sample.pitch_deg,
                'roll_deg': obj.closest_nav_sample.roll_deg
            }
        return None
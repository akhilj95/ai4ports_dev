from django.contrib import admin
from . import models

admin.site.register(models.RoverHardware)
admin.site.register(models.Sensor)
admin.site.register(models.Calibration)
admin.site.register(models.Location)
admin.site.register(models.Mission)
admin.site.register(models.SensorDeployment)
admin.site.register(models.NavSample)
admin.site.register(models.LogFile)
admin.site.register(models.MediaAsset)
admin.site.register(models.FrameIndex)
admin.site.register(models.ImuSample)
admin.site.register(models.CompassSample)
admin.site.register(models.PressureSample)
admin.site.register(models.TideLevel)
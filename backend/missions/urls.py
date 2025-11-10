from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"rovers", views.RoverHardwareViewSet)
router.register(r"sensors", views.SensorViewSet)
router.register(r"calibrations", views.CalibrationViewSet)
router.register(r"missions", views.MissionViewSet)
router.register(r"deployments", views.SensorDeploymentViewSet)
router.register(r"logfiles", views.LogFileViewSet)
router.register(r"navsamples", views.NavSampleViewSet)
router.register(r"imusamples", views.ImuSampleViewSet)
router.register(r"compasssamples", views.CompassSampleViewSet)
router.register(r"pressuresamples", views.PressureSampleViewSet)
router.register(r'media-assets', views.MediaAssetViewSet)
router.register(r'frame-indices', views.FrameIndexViewSet)
router.register(r'tide-levels', views.TideLevelViewSet)

urlpatterns = router.urls
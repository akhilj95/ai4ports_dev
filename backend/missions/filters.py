import django_filters as filters
from missions.models import Mission
from missions.models import MediaAsset

class MissionFilter(filters.FilterSet):
    start_after = filters.DateTimeFilter(field_name="start_time", lookup_expr="gte")
    start_before = filters.DateTimeFilter(field_name="start_time", lookup_expr="lte")
    max_depth__lt = filters.NumberFilter(field_name="max_depth", lookup_expr="lt")
    target_type = filters.CharFilter(lookup_expr="iexact")
    location_name = filters.CharFilter(field_name="location__name", lookup_expr="iexact")

    class Meta:
        model = Mission
        fields = ["rover__name", "target_type"]


class MediaAssetFilter(filters.FilterSet):
    location = filters.CharFilter(
        field_name='deployment__mission__location__name', 
        lookup_expr='iexact'
    )
    depth_min = filters.NumberFilter(
        field_name='max_depth_m', 
        lookup_expr='gte'
    )
    depth_max = filters.NumberFilter(
        field_name='min_depth_m',
        lookup_expr='lte'
    )
    yaw_min = filters.NumberFilter(
        field_name='frames__closest_nav_sample__yaw_deg',
        lookup_expr='gte'
    )
    yaw_max = filters.NumberFilter(
        field_name='frames__closest_nav_sample__yaw_deg',
        lookup_expr='lte'
    )
    
    class Meta:
        model = MediaAsset
        fields = {
            'media_type': ['exact'],
            'start_time': ['gte', 'lte'],
            'deployment__mission': ['exact'],
            'deployment__sensor': ['exact'],
            'deployment__sensor__sensor_type': ['exact'],
        }
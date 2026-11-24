from urllib.parse import urlencode

from store.models import ShopLocation


def current_location():
    return ShopLocation.objects.exclude(address="").filter(pk=1).first()


def location_details(address, is_example):
    if not address:
        return None
    query = urlencode({"api": 1, "destination": address})
    url = "https://www.google.com/maps/dir/?" + query
    return {
        "address": address,
        "is_example": is_example,
        "map_url": url if len(url) <= 2048 else "",
    }

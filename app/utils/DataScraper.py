import requests
from typing import Optional, cast, List, Dict, Any
from geopy.geocoders import Nominatim
from geopy.location import Location
from math import radians, cos, sin, sqrt, atan2
from starlette.concurrency import run_in_threadpool
from fastapi import HTTPException # Keep HTTPException for potential use within the function

# Type mapping for OSM
TYPE_MAPPING = {
    "restaurant": [
        {"key": "amenity", "value": "restaurant"},
        {"key": "amenity", "value": "fast_food"},
        {"key": "amenity", "value": "cafe"},
    ],
    "cafe": [
        {"key": "amenity", "value": "cafe"},
        {"key": "amenity", "value": "coffee_shop"},
    ],
    "bar": [
        {"key": "amenity", "value": "bar"},
        {"key": "amenity", "value": "pub"},
    ],
    "hotel": [
        {"key": "tourism", "value": "hotel"},
        {"key": "tourism", "value": "guest_house"},
        {"key": "tourism", "value": "motel"},
        {"key": "tourism", "value": "hostel"},
    ],
    "pg": [  # Indian-style paying guest
        {"key": "tourism", "value": "guest_house"},
        {"key": "amenity", "value": "guest_house"},
    ],
    "hostel": [
        {"key": "tourism", "value": "hostel"},
    ],
    "pharmacy": [
        {"key": "amenity", "value": "pharmacy"},
    ],
    "hospital": [
        {"key": "amenity", "value": "hospital"},
        {"key": "amenity", "value": "clinic"},
    ],
    "school": [
        {"key": "amenity", "value": "school"},
    ],
    "college": [
        {"key": "amenity", "value": "college"},
    ],
    "university": [
        {"key": "amenity", "value": "university"},
    ],
    "bank": [
        {"key": "amenity", "value": "bank"},
    ],
    "atm": [
        {"key": "amenity", "value": "atm"},
    ],
    "supermarket": [
        {"key": "shop", "value": "supermarket"},
        {"key": "shop", "value": "hypermarket"},
    ],
    "grocery": [
        {"key": "shop", "value": "convenience"},
        {"key": "shop", "value": "general_store"},
    ],
    "mall": [
        {"key": "shop", "value": "mall"},
        {"key": "shop", "value": "department_store"},
    ],
    "gym": [
        {"key": "leisure", "value": "fitness_centre"},
        {"key": "sport", "value": "fitness"},
    ],
}


# Calculate distance (Haversine formula)
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


async def search_places(
    location: str,
    type: str,
    radius: int,
    limit: int
) -> Dict[str, Any]:
    # Step 1: Geocode location
    geolocator = Nominatim(user_agent="osm_api")
    loc: Optional[Location] = cast(Optional[Location], await run_in_threadpool(geolocator.geocode, location))
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    lat, lon = loc.latitude, loc.longitude

    # Step 2: Map type → OSM tag
    osm_info = TYPE_MAPPING.get(type.lower())
    if not osm_info:
        raise HTTPException(status_code=400, detail=f"Unsupported type: {type}")

    results = []
    for filter_item in osm_info:
        query = f"""
        [out:json][timeout:25];
        node[{filter_item['key']}={filter_item['value']}](around:{radius},{lat},{lon});
        out body;
        """
        url = "https://overpass-api.de/api/interpreter"
        response = requests.post(url, data={"data": query})
        data = response.json()

        for element in data.get("elements", []):
            if "tags" not in element:
                continue
            name = element["tags"].get("name")
            if not name:
                continue

            el_lat, el_lon = element["lat"], element["lon"]
            distance = calculate_distance(lat, lon, el_lat, el_lon)

            results.append({
                "name": name,
                "address": element["tags"].get("addr:full") or element["tags"].get("addr:street"),
                "latitude": el_lat,
                "longitude": el_lon,
                "osmLink": f"https://www.openstreetmap.org/?mlat={el_lat}&mlon={el_lon}&zoom=18",
                "ward": element["tags"].get("addr:suburb") or "",
                "city": element["tags"].get("addr:city") or "Kolkata",
                "state": element["tags"].get("addr:state") or "West Bengal",
                "country": element["tags"].get("addr:country") or "India",
                "type": type,
                "distance_km": round(distance, 2)
            })

    # Step 4: Limit results
    results = sorted(results, key=lambda x: x["distance_km"])[:limit]
    return {"query": location, "types": [type], "radius": radius, "results": results}

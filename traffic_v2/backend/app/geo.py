import math


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rank_authorities(authorities, lat, lng, types, max_km, per_type=3):
    """For each wanted type: active authorities within max_km, nearest first (top per_type).

    Returns {type: [ {..authority.., "distance_km": x}, ... ]}
    """
    out = {}
    for t in types:
        cand = []
        for a in authorities:
            if a["type"] != t or not a.get("active", 1):
                continue
            d = haversine_km(lat, lng, a["lat"], a["lng"])
            if d <= max_km:
                cand.append({**a, "distance_km": round(d, 2)})
        cand.sort(key=lambda a: a["distance_km"])
        out[t] = cand[:per_type]
    return out


def maps_link(lat, lng):
    return f"https://www.google.com/maps?q={lat:.6f},{lng:.6f}"

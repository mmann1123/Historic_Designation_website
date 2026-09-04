#!/usr/bin/env python3
"""Refresh the GeoJSON snapshots behind map.html from Open Data DC.

Run from the repo root:  python3 scripts/fetch_map_data.py

Pulls three layers from the DC GIS ArcGIS REST services, trims them to the
fields the map uses, rounds coordinates, and writes them to assets/data/.
No third-party packages required.
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "data")

BASE = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA"
HOUSING = BASE + "/Property_and_Land_WebMercator/MapServer/62/query"
HISTORIC = BASE + "/Historic_WebMercator/MapServer/6/query"
ZONING = BASE + "/Planning_Landuse_and_Zoning_WebMercator/MapServer/32/query"

SINGLE_FAMILY_WHERE = (
    "ZONING LIKE 'R-1A%' OR ZONING LIKE 'R-1B%' "
    "OR ZONING LIKE 'R-2%' OR ZONING LIKE 'R-3%'"
)


def query(url, where, fields):
    """Fetch every feature (paging past the server's record limit) as GeoJSON."""
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": where, "outFields": fields, "outSR": 4326, "f": "geojson",
            "resultOffset": offset, "resultRecordCount": 1000,
        })
        with urllib.request.urlopen(url + "?" + q, timeout=120) as r:
            d = json.load(r)
        if "error" in d:
            raise SystemExit("ArcGIS error from %s: %s" % (url, d["error"]))
        feats.extend(d["features"])
        if not d.get("exceededTransferLimit") and not (d.get("properties") or {}).get("exceededTransferLimit"):
            break
        offset += len(d["features"])
    return feats


def rnd(c, p):
    if isinstance(c[0], (int, float)):
        return [round(c[0], p), round(c[1], p)]
    return [rnd(x, p) for x in c]


def dedupe(coords):
    if not isinstance(coords[0][0], (int, float)):
        return [dedupe(c) for c in coords]
    out = [coords[0]]
    for c in coords[1:]:
        if c != out[-1]:
            out.append(c)
    return out


def day(ms):
    if not ms:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")


def write(name, feats):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, separators=(",", ":"))
    print("wrote %s (%d features, %.0f KB)" % (path, len(feats), os.path.getsize(path) / 1024))


def main():
    print("Affordable housing ...")
    raw = query(HOUSING, "1=1",
                "PROJECT_NAME,ADDRESS,STATUS_PUBLIC,AGENCY_CALCULATED,TOTAL_AFFORDABLE_UNITS,"
                "AFFORDABLE_UNITS_AT_0_30_AMI,AFFORDABLE_UNITS_AT_31_50_AMI,AFFORDABLE_UNITS_AT_51_60_AMI,"
                "AFFORDABLE_UNITS_AT_61_80_AMI,AFFORDABLE_UNITS_AT_81_AMI,UNITS_TOTAL,MAR_WARD,CONSTRUCTION_END_DATE")
    feats = []
    for f in raw:
        if not f.get("geometry"):
            continue
        p = f["properties"]
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": rnd(f["geometry"]["coordinates"], 6)},
                      "properties": {
                          "name": p["PROJECT_NAME"], "address": p["ADDRESS"], "status": p["STATUS_PUBLIC"],
                          "agency": p["AGENCY_CALCULATED"], "aff": p["TOTAL_AFFORDABLE_UNITS"] or 0,
                          "total": p["UNITS_TOTAL"], "ward": p["MAR_WARD"], "end": day(p["CONSTRUCTION_END_DATE"]),
                          "ami": [p["AFFORDABLE_UNITS_AT_0_30_AMI"] or 0, p["AFFORDABLE_UNITS_AT_31_50_AMI"] or 0,
                                  p["AFFORDABLE_UNITS_AT_51_60_AMI"] or 0, p["AFFORDABLE_UNITS_AT_61_80_AMI"] or 0,
                                  p["AFFORDABLE_UNITS_AT_81_AMI"] or 0]}})
    write("affordable_housing.geojson", feats)

    print("Historic districts ...")
    raw = query(HISTORIC, "1=1", "NAME,LABEL,DESIGNATION,DESIGNATION_DATE,NR")
    feats = [{"type": "Feature",
              "geometry": {"type": f["geometry"]["type"], "coordinates": dedupe(rnd(f["geometry"]["coordinates"], 5))},
              "properties": {"name": f["properties"]["NAME"], "label": f["properties"]["LABEL"],
                             "designation": f["properties"]["DESIGNATION"],
                             "date": day(f["properties"]["DESIGNATION_DATE"]), "nr": f["properties"]["NR"]}}
             for f in raw if f.get("geometry")]
    write("historic_districts.geojson", feats)

    print("Single-family zoning (R-1A, R-1B, R-2, R-3) ...")
    raw = query(ZONING, SINGLE_FAMILY_WHERE, "ZONING,ZONING_LABEL,ZONE_DESCRIPTION")
    feats = [{"type": "Feature",
              "geometry": {"type": f["geometry"]["type"], "coordinates": dedupe(rnd(f["geometry"]["coordinates"], 5))},
              "properties": {"zone": f["properties"]["ZONING"], "label": f["properties"]["ZONING_LABEL"],
                             "desc": f["properties"]["ZONE_DESCRIPTION"]}}
             for f in raw if f.get("geometry")]
    write("single_family_zoning.geojson", feats)
    print("Done. Update the 'Data retrieved' date in map.html if you like.")


if __name__ == "__main__":
    sys.exit(main())

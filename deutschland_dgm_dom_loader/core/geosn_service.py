import json
import urllib.parse
import urllib.request

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject
)


MAPSERVER_URL = (
    "https://geodienste.sachsen.de/ags-relay/ArcGISServer/guest/"
    "arcgis/rest/services/geosn/rest_geosn_downloadlinks/MapServer"
)

PRODUCT_LAYER_IDS = {
    "DOM1": 4,
    "DGM1": 6,
}


def layer_id_for_product(product: str) -> int:
    product = product.upper().strip()
    if product not in PRODUCT_LAYER_IDS:
        raise ValueError(f"Unsupported product: {product}")
    return PRODUCT_LAYER_IDS[product]


def transform_extent_to_25833(extent, source_crs):
    target_crs = QgsCoordinateReferenceSystem("EPSG:25833")
    if source_crs == target_crs:
        return extent

    transform = QgsCoordinateTransform(
        source_crs,
        target_crs,
        QgsProject.instance()
    )
    return transform.transformBoundingBox(extent)


def extent_to_esri_geometry_json(extent_25833) -> str:
    geom = {
        "xmin": extent_25833.xMinimum(),
        "ymin": extent_25833.yMinimum(),
        "xmax": extent_25833.xMaximum(),
        "ymax": extent_25833.yMaximum(),
        "spatialReference": {"wkid": 25833}
    }
    return json.dumps(geom, separators=(",", ":"))


def build_query_url(extent, source_crs, product: str, out_fields=None) -> str:
    if out_fields is None:
        out_fields = ["Produkt", "Kachel", "Download", "Stand"]

    layer_id = layer_id_for_product(product)
    extent_25833 = transform_extent_to_25833(extent, source_crs)
    geom_json = extent_to_esri_geometry_json(extent_25833)

    params = {
        "f": "json",
        "where": "1=1",
        "geometry": geom_json,
        "geometryType": "esriGeometryEnvelope",
        "inSR": 25833,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "false",
        "outFields": ",".join(out_fields),
    }

    return f"{MAPSERVER_URL}/{layer_id}/query?{urllib.parse.urlencode(params)}"


def query_tiles_for_extent(extent, source_crs, product: str, timeout: int = 30) -> list[dict]:
    url = build_query_url(extent, source_crs, product)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "QGIS Sachsen DGM Loader/0.2.0"}
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    if "error" in data:
        err = data["error"]
        raise RuntimeError(
            f"GeoSN service error {err.get('code')}: {err.get('message')}"
        )

    features = data.get("features", [])
    results = []

    for feat in features:
        attrs = feat.get("attributes", {}) or {}
        results.append({
            "produkt": attrs.get("Produkt"),
            "kachel": attrs.get("Kachel"),
            "download": attrs.get("Download"),
            "stand": attrs.get("Stand"),
        })

    return results
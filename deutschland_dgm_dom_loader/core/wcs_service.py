import os
import time
import math
import urllib.parse
import urllib.request
import re
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from osgeo import gdal
except Exception:
    gdal = None

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle


# WCS providers handled via GetCoverage instead of file-link catalogues.
# Sachsen-Anhalt and Brandenburg are kept in their provider/native CRS first.
WCS_PROVIDERS = {
    "Sachsen-Anhalt": {
        "target_authid": "EPSG:25832",
        "nodata": -99999,
        "services": {
            "DGM1": [
                "https://www.geodatenportal.sachsen-anhalt.de/wss/service/ST_LVermGeo_DGM1_WCS_OpenData/guest",
                "https://geodatenportal.sachsen-anhalt.de/ows_INSPIRE_LVermGeo_ATKIS_EL_DGM_WCS",
            ],
            "DOM1": [
                "https://geodatenportal.sachsen-anhalt.de/ows_INSPIRE_LVermGeo_ATKIS_EL_DOM_WCS",
            ],
        },
    },
    "Brandenburg": {
        # Direct LGB OpenData tiles are numeric height grids. The public WCS
        # dgm_wcs/bdom_wcs is a rendered RGB/shaded product and is not suitable
        # for DGM/DOM analysis.
        "target_authid": "EPSG:25833",
        "nodata": -9999,
        "direct_download": True,
        "tile_size": 1000,
        "max_workers": 6,
        "base_urls": {
            "DGM1": "https://data.geobasis-bb.de/geobasis/daten/dgm/tif/",
            "DOM1": "https://data.geobasis-bb.de/geobasis/daten/bdom/tif/",
        },
        "file_prefix": {
            "DGM1": "dgm",
            "DOM1": "bdom",
        },
        "services": {},
    },
    "Bayern": {
        # Bayerische Vermessungsverwaltung OpenData.
        # DGM1 is still resolved through the official Metalink catalogue.
        # DOM20 uses direct BayernWolke GeoTIFF URLs, e.g.
        # https://download1.bayernwolke.de/a/dom20/DOM/32676_5479_20_DOM.tif
        "target_authid": "EPSG:25832",
        "nodata": -9999,
        "direct_download": True,
        "tile_size": 1000,
        "max_workers": 6,
        "products": {
            "DGM1": {
                "metalink_url": "https://geodaten.bayern.de/odd/a/dgm/dgm1/meta/metalink/09.meta4",
                "direct_url_templates": [
                    "https://download1.bayernwolke.de/a/dgm/dgm1/{name}",
                    "https://download2.bayernwolke.de/a/dgm/dgm1/{name}",
                    "https://geodaten.bayern.de/odd/a/dgm/dgm1/{name}",
                ],
            },
            "DOM20": {
                "skip_metalink": True,
                "direct_url_templates": [
                    "https://download1.bayernwolke.de/a/dom20/DOM/{name}",
                    "https://download2.bayernwolke.de/a/dom20/DOM/{name}",
                ],
            },
        },
        "services": {},
    },
}

NODATA_VALUE = -99999
CRS_25832_URI = "http://www.opengis.net/def/crs/EPSG/0/25832"
CRS_4326_URI = "http://www.opengis.net/def/crs/EPSG/0/4326"


def transform_extent(extent, source_crs, target_authid="EPSG:25832"):
    target_crs = QgsCoordinateReferenceSystem(target_authid)
    if source_crs == target_crs:
        return extent
    tr = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
    return tr.transformBoundingBox(extent)


def _extent_4326_from_25832(extent_25832):
    src = QgsCoordinateReferenceSystem("EPSG:25832")
    dst = QgsCoordinateReferenceSystem("EPSG:4326")
    tr = QgsCoordinateTransform(src, dst, QgsProject.instance())
    return tr.transformBoundingBox(extent_25832)


def _open_url(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "QGIS Sachsen DGM/DOM Loader"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers), getattr(resp, "url", url)


def _provider_config(provider="Sachsen-Anhalt"):
    provider = provider or "Sachsen-Anhalt"
    if provider not in WCS_PROVIDERS:
        raise ValueError(f"Unsupported WCS provider: {provider}")
    return WCS_PROVIDERS[provider]


def provider_target_authid(provider="Sachsen-Anhalt"):
    return _provider_config(provider).get("target_authid", "EPSG:25832")


def provider_nodata(provider="Sachsen-Anhalt"):
    return _provider_config(provider).get("nodata", NODATA_VALUE)


def _service_urls(product, provider="Sachsen-Anhalt"):
    key = (product or "").upper()
    cfg = _provider_config(provider)
    if cfg.get("direct_download"):
        raise ValueError(f"{provider} uses direct OpenData tile downloads, not WCS capabilities.")
    services = cfg.get("services", {})
    if key not in services:
        raise ValueError(f"Unsupported {provider} WCS product: {product}")
    return services[key]


def _capabilities_url(base_url, version=None):
    params = {"SERVICE": "WCS", "REQUEST": "GetCapabilities"}
    if version:
        params["VERSION"] = version
    return base_url + "?" + urllib.parse.urlencode(params)


def _tag_name(elem):
    return elem.tag.split("}")[-1].lower()


def parse_coverage_ids(xml_bytes):
    ids = []
    root = ET.fromstring(xml_bytes)
    for elem in root.iter():
        name = _tag_name(elem)
        if name in ("coverageid", "identifier", "name") and elem.text:
            text = elem.text.strip()
            if text and text not in ids:
                ids.append(text)
    cleaned = []
    for cid in ids:
        low = cid.lower()
        if any(token in low for token in ("dgm", "dom", "coverage", "relief", "elevation", "height", "el_")):
            cleaned.append(cid)
    return cleaned or ids


def get_coverage_ids_for_url(base_url, log=None):
    last_error = None
    # Try without VERSION first. The Sachsen-Anhalt catalogue advertises this form.
    for version in (None, "2.0.1", "1.1.1", "1.0.0"):
        url = _capabilities_url(base_url, version)
        try:
            if log:
                log(f"Reading WCS GetCapabilities ({version or 'default'})...")
            data, _, _ = _open_url(url, timeout=60)
            ids = parse_coverage_ids(data)
            if ids:
                if log:
                    log("Available coverage id candidates: " + ", ".join(ids[:12]))
                return ids
        except Exception as e:
            last_error = e
            if log:
                log(f"GetCapabilities {version or 'default'} failed: {e}")
    if last_error:
        raise RuntimeError(f"Could not read WCS GetCapabilities: {last_error}")
    raise RuntimeError("Could not read WCS GetCapabilities: no coverage ids found.")



def get_coverage_ids(product, log=None, provider="Sachsen-Anhalt"):
    """Backward-compatible helper used by the dialog.

    Returns coverage id candidates for all configured Sachsen-Anhalt WCS endpoints
    of the selected product.
    """
    ids_all = []
    last_error = None
    for base_url in _service_urls(product, provider=provider):
        try:
            ids = get_coverage_ids_for_url(base_url, log=log)
            for cid in ids:
                if cid not in ids_all:
                    ids_all.append(cid)
        except Exception as e:
            last_error = e
            if log:
                log(f"GetCapabilities failed for {base_url}: {e}")
    if ids_all:
        return ids_all
    if last_error:
        raise RuntimeError(f"Could not read WCS GetCapabilities: {last_error}")
    raise RuntimeError("Could not read WCS GetCapabilities: no coverage ids found.")


def choose_coverage_id(product, ids, base_url=None):
    """Choose the usable WCS coverage identifier.

    QGIS reports the Sachsen-Anhalt DGM1 and DOM1 WCS as WCS 1.0.0
    with coverage identifier "1". The visible layer titles are DGM1 /
    ElevationGridCoverage_DOM1, but GetCoverage must use COVERAGE=1.
    """
    product_upper = (product or "").upper()
    url_low = (base_url or "").lower()

    if product_upper in ("DGM1", "DOM1") and (
        "st_lvermgeo_dgm1_wcs_opendata" in url_low
        or "ows_inspire_lvermgeo_atkis_el_dom_wcs" in url_low
        or "ows_inspire_lvermgeo_atkis_el_dgm_wcs" in url_low
    ):
        return "1"

    for cid in ids or []:
        if str(cid).strip() == "1":
            return "1"

    preferred = {
        "DGM1": ["dgm1", "el_dgm", "dgm"],
        "DOM1": ["dom1", "el_dom", "dom", "elevationgridcoverage_dom1"],
    }.get(product_upper, [])
    for token in preferred:
        for cid in ids or []:
            if token in str(cid).lower():
                return cid
    return ids[0] if ids else "1"


def _build_url(base_url, params):
    return base_url + "?" + urllib.parse.urlencode(params, doseq=True, safe=":,()/")


def _aligned_extent(ext):
    # DGM/DOM 1 m services are commonly sensitive to sub-pixel decimal BBOX values.
    xmin = math.floor(ext.xMinimum())
    ymin = math.floor(ext.yMinimum())
    xmax = math.ceil(ext.xMaximum())
    ymax = math.ceil(ext.yMaximum())
    return QgsRectangle(xmin, ymin, xmax, ymax)


def _candidate_getcoverage_urls(base_url, coverage_id, extent_target, target_authid="EPSG:25832"):
    """Build a compact set of GetCoverage URLs for the Sachsen-Anhalt WCS.

    QGIS identifies both tested Sachsen-Anhalt services as WCS 1.0.0 with
    COVERAGE=1. The previously broad WCS 2.0/1.1 fallback matrix produced
    many unnecessary HTTP 500 requests. This reduced list keeps the working
    QGIS-compatible request pattern first and only tries a few pragmatic
    format/parameter fallbacks.
    """
    e = _aligned_extent(extent_target)
    xmin, xmax = e.xMinimum(), e.xMaximum()
    ymin, ymax = e.yMinimum(), e.yMaximum()
    width = max(1, int(round(xmax - xmin)))
    height = max(1, int(round(ymax - ymin)))

    # Variant 1 is the request form that worked against the DGM1 endpoint
    # once FORMAT=GeoTIFF was used instead of GEOTIFF_FLOAT32.
    formats = ["GeoTIFF", "GEOTIFF", "GTiff", "image/tiff", "GEOTIFF_FLOAT32"]

    seen = set()
    for fmt in formats:
        variants = [
            {
                "SERVICE": "WCS",
                "VERSION": "1.0.0",
                "REQUEST": "GetCoverage",
                "COVERAGE": coverage_id,
                "CRS": target_authid,
                "RESPONSE_CRS": target_authid,
                "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
                "WIDTH": width,
                "HEIGHT": height,
                "FORMAT": fmt,
            },
            {
                "SERVICE": "WCS",
                "VERSION": "1.0.0",
                "REQUEST": "GetCoverage",
                "COVERAGE": coverage_id,
                "CRS": target_authid,
                "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
                "WIDTH": width,
                "HEIGHT": height,
                "FORMAT": fmt,
            },
            {
                "SERVICE": "WCS",
                "VERSION": "1.0.0",
                "REQUEST": "GetCoverage",
                "COVERAGE": coverage_id,
                "CRS": target_authid,
                "RESPONSE_CRS": target_authid,
                "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
                "RESX": 1,
                "RESY": 1,
                "FORMAT": fmt,
            },
        ]
        for params in variants:
            url = _build_url(base_url, params)
            if url not in seen:
                seen.add(url)
                yield url, False


def _looks_like_tiff(data):
    return data[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


def _is_xml_error(data):
    head = data[:500].lstrip().lower()
    return head.startswith(b"<") and (b"exception" in head or b"serviceexception" in head or b"html" in head or b"error" in head)


def _split_extent(extent_target, max_edge_m=800.0):
    e = _aligned_extent(extent_target)
    xmin, xmax = e.xMinimum(), e.xMaximum()
    ymin, ymax = e.yMinimum(), e.yMaximum()
    width = max(0.0, xmax - xmin)
    height = max(0.0, ymax - ymin)
    if width <= max_edge_m and height <= max_edge_m:
        return [e]
    nx = max(1, int(math.ceil(width / max_edge_m)))
    ny = max(1, int(math.ceil(height / max_edge_m)))
    dx = width / nx
    dy = height / ny
    tiles = []
    for iy in range(ny):
        y0 = ymin + iy * dy
        y1 = ymax if iy == ny - 1 else ymin + (iy + 1) * dy
        for ix in range(nx):
            x0 = xmin + ix * dx
            x1 = xmax if ix == nx - 1 else xmin + (ix + 1) * dx
            tiles.append(QgsRectangle(math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)))
    return tiles


def _download_single_wcs_tile(base_url, coverage_id, tile_extent_target, out_path, log=None, is_canceled=None, tile_label="", target_authid="EPSG:25832"):
    error_messages = []
    prefix = f"{tile_label}: " if tile_label else ""
    candidates = list(_candidate_getcoverage_urls(base_url, coverage_id, tile_extent_target, target_authid=target_authid))
    if log:
        log(f"{prefix}Manual GetCoverage variants: {len(candidates)}")
        if candidates:
            log(f"{prefix}GetCoverage URL: {candidates[0][0]}")

    for idx, (url, _needs_warp) in enumerate(candidates, start=1):
        if is_canceled and is_canceled():
            raise RuntimeError("Canceled")
        try:
            if log:
                log(f"{prefix}Trying WCS GetCoverage variant {idx}/{len(candidates)}...")
            data, headers, final_url = _open_url(url, timeout=300)
            ctype = str(headers.get("Content-Type", ""))
            if _is_xml_error(data) or not _looks_like_tiff(data):
                msg = data[:1200].decode("utf-8", errors="ignore").replace("\n", " ")
                error_messages.append(f"Variant {idx} returned non-TIFF ({ctype}): {msg[:600]}")
                if log:
                    log(f"{prefix}Variant {idx} returned non-TIFF ({ctype}): {msg[:300]}")
                continue
            with open(out_path, "wb") as fh:
                fh.write(data)
            if gdal is not None:
                try:
                    ds = gdal.Open(out_path, gdal.GA_Update)
                    if ds:
                        band = ds.GetRasterBand(1)
                        if band:
                            band.SetNoDataValue(NODATA_VALUE)
                        ds = None
                except Exception:
                    pass
            return out_path
        except Exception as e:
            body = ""
            try:
                if hasattr(e, "read"):
                    body = e.read(1200).decode("utf-8", errors="ignore").replace("\n", " ")
            except Exception:
                body = ""
            detail = f"{e}"
            if body:
                detail += f" | {body[:600]}"
            error_messages.append(f"Variant {idx} failed: {detail}")
            if log:
                log(f"{prefix}Variant {idx} failed: {detail[:700]}")

    details = "\n".join(error_messages[-12:])
    raise RuntimeError("All WCS GetCoverage variants failed. Last messages:\n" + details)



def _download_file(url, out_path, log=None, timeout=300):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        if log:
            log(f"Using existing ZIP: {os.path.basename(out_path)}")
        return out_path
    if log:
        log(f"Downloading: {url}")
    data, headers, final_url = _open_url(url, timeout=timeout)
    if _is_xml_error(data) or data[:2] != b"PK":
        ctype = str(headers.get("Content-Type", ""))
        msg = data[:800].decode("utf-8", errors="ignore").replace("\n", " ")
        raise RuntimeError(f"Download did not return a ZIP ({ctype}): {msg[:400]}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp_path = out_path + ".part"
    with open(tmp_path, "wb") as fh:
        fh.write(data)
    os.replace(tmp_path, out_path)
    return out_path


def _download_tiff_file(url, out_path, log=None, timeout=300):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        if log:
            log(f"Using existing GeoTIFF: {os.path.basename(out_path)}")
        return out_path
    if log:
        log(f"Downloading: {url}")
    data, headers, final_url = _open_url(url, timeout=timeout)
    if _is_xml_error(data) or not _looks_like_tiff(data):
        ctype = str(headers.get("Content-Type", ""))
        msg = data[:800].decode("utf-8", errors="ignore").replace("\n", " ")
        raise RuntimeError(f"Download did not return a GeoTIFF ({ctype}): {msg[:400]}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp_path = out_path + ".part"
    with open(tmp_path, "wb") as fh:
        fh.write(data)
    os.replace(tmp_path, out_path)
    return out_path



def _discover_bayern_metalinks_from_detail(product_cfg, log=None):
    """Scrape the public Bayern OpenData product detail page for .meta4 links.

    The OpenData detail pages are partly generated by the portal and the exact
    product path may change. This lightweight discovery avoids hard-coding a
    single DOM20 path and keeps future products easier to add.
    """
    detail_url = product_cfg.get("opendata_detail_url")
    if not detail_url:
        return []
    try:
        data, _headers, final_url = _open_url(detail_url, timeout=60)
        html = data.decode("utf-8", errors="ignore")
    except Exception as e:
        if log:
            log(f"Bayern OpenData detail discovery failed: {detail_url} | {e}")
        return []

    urls = []
    # Absolute links in href/src/text.
    for m in re.finditer(r'https://[^\s"\'<>()]+?\.meta4', html, flags=re.IGNORECASE):
        urls.append(m.group(0))
    # Relative OpenData links, e.g. /odd/a/dgm/dgm1/meta/metalink/09.meta4
    for m in re.finditer(r'/(?:odd|opengeodata)/[^\s"\'<>()]+?\.meta4', html, flags=re.IGNORECASE):
        urls.append(urllib.parse.urljoin(final_url, m.group(0)))
    # Sometimes the portal HTML encodes slashes.
    html_unescaped = html.replace('\\/', '/')
    for m in re.finditer(r'https://[^\s"\'<>()]+?\.meta4', html_unescaped, flags=re.IGNORECASE):
        urls.append(m.group(0))
    for m in re.finditer(r'/(?:odd|opengeodata)/[^\s"\'<>()]+?\.meta4', html_unescaped, flags=re.IGNORECASE):
        urls.append(urllib.parse.urljoin(final_url, m.group(0)))

    cleaned = []
    for u in urls:
        u = u.replace('&amp;', '&').strip()
        if u not in cleaned:
            cleaned.append(u)
    if log and cleaned:
        log(f"Bayern OpenData detail discovery found {len(cleaned)} Metalink URL candidate(s).")
    return cleaned

def _parse_bayern_metalink(product_cfg, log=None):
    urls = []
    urls.extend(_discover_bayern_metalinks_from_detail(product_cfg, log=log))
    if product_cfg.get("metalink_url"):
        urls.append(product_cfg.get("metalink_url"))
    urls.extend(product_cfg.get("metalink_url_candidates", []))

    # De-duplicate while preserving order.
    deduped = []
    for u in urls:
        if u and u not in deduped:
            deduped.append(u)
    urls = deduped

    last_error = None
    for url in urls:
        try:
            data, _headers, _final_url = _open_url(url, timeout=120)
            root = ET.fromstring(data)
            result = {}
            for file_elem in root.iter():
                if _tag_name(file_elem) != "file":
                    continue
                name = file_elem.attrib.get("name")
                if not name:
                    continue
                url_list = []
                for child in file_elem.iter():
                    if _tag_name(child) == "url" and child.text:
                        url_list.append(child.text.strip())
                if url_list:
                    result[name] = url_list
            if result:
                if log:
                    log(f"Bayern Metalink entries loaded: {len(result)} from {url}")
                return result
            last_error = RuntimeError(f"Metalink contained no file entries: {url}")
        except Exception as e:
            last_error = e
            if log:
                log(f"Bayern Metalink candidate failed: {url} | {e}")
    if last_error:
        raise last_error
    return {}


def _name_variants_bayern(name, product=None):
    base = os.path.splitext(name)[0]
    parts = base.split("_")
    x = parts[0] if len(parts) >= 2 else ""
    y = parts[1] if len(parts) >= 2 else ""

    if str(product or "").upper() == "DOM20" and x and y:
        # Confirmed DOM20 BayernWolke naming: 32 + easting-km, northing-km, 20_DOM.
        return [f"32{x}_{y}_20_DOM.tif"]

    variants = [name]
    bases = [base]

    # Product and CRS-prefixed filename variants used by different BVV products.
    for prefix in ("dom20_", "bdom20_", "dgm1_", "dgm_dom20_", "dgm_bdom20_"):
        bases.append(prefix + base)
    if x and y:
        # DOM20 uses the full UTM32 kilometre code in the filename: 32 + easting_km,
        # e.g. easting 676 km / northing 5479 km -> 32676_5479_20_DOM.tif.
        # The direct URL folder is /a/dom20/DOM/.
        dom20_base = f"32{x}_{y}_20_DOM"
        bases.append(dom20_base)
        # Keep common alternatives as fallback for DGM1 or older BVV layouts.
        for b in (f"32_{x}_{y}", f"32{x}_{y}", f"utm32_{x}_{y}", f"utm32n_{x}_{y}"):
            bases.append(b)
            for prefix in ("dom20_", "bdom20_", "dgm1_"):
                bases.append(prefix + b)

    for b in bases:
        for ext in (".tif", ".zip", ".tiff"):
            cand = b + ext
            if cand not in variants:
                variants.append(cand)
    return variants


def _download_bayern_raster_candidate(url, out_path, log=None, timeout=300):
    data, headers, final_url = _open_url(url, timeout=timeout)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lower_url = urllib.parse.urlparse(final_url).path.lower()
    ctype = str(headers.get("Content-Type", "")).lower()

    if data[:2] == b"PK" or lower_url.endswith(".zip") or "zip" in ctype:
        zip_path = out_path if out_path.lower().endswith(".zip") else os.path.splitext(out_path)[0] + ".zip"
        tmp_path = zip_path + ".part"
        with open(tmp_path, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, zip_path)
        extract_dir = os.path.splitext(zip_path)[0] + "_extracted"
        rasters = _extract_rasters_from_zip(zip_path, extract_dir, log=log)
        return rasters[0]

    if _is_xml_error(data) or not _looks_like_tiff(data):
        msg = data[:800].decode("utf-8", errors="ignore").replace("\n", " ")
        raise RuntimeError(f"Download did not return a GeoTIFF/ZIP ({ctype}): {msg[:400]}")

    tif_path = out_path if out_path.lower().endswith((".tif", ".tiff")) else os.path.splitext(out_path)[0] + ".tif"
    tmp_path = tif_path + ".part"
    with open(tmp_path, "wb") as fh:
        fh.write(data)
    os.replace(tmp_path, tif_path)
    return tif_path

def _bayern_tile_names(extent_25832, tile_size=1000):
    e = _aligned_extent(extent_25832)
    xmin, xmax = e.xMinimum(), e.xMaximum()
    ymin, ymax = e.yMinimum(), e.yMaximum()
    eps = 1e-6
    x0 = int(math.floor(xmin / tile_size))
    x1 = int(math.floor((xmax - eps) / tile_size))
    y0 = int(math.floor(ymin / tile_size))
    y1 = int(math.floor((ymax - eps) / tile_size))
    names = []
    for ykm in range(y0, y1 + 1):
        for xkm in range(x0, x1 + 1):
            names.append(f"{xkm}_{ykm}.tif")
    return names

def _brandenburg_tile_codes(extent_25833, tile_size=1000):
    e = _aligned_extent(extent_25833)
    xmin, xmax = e.xMinimum(), e.xMaximum()
    ymin, ymax = e.yMinimum(), e.yMaximum()
    eps = 1e-6
    x0 = int(math.floor(xmin / tile_size))
    x1 = int(math.floor((xmax - eps) / tile_size))
    y0 = int(math.floor(ymin / tile_size))
    y1 = int(math.floor((ymax - eps) / tile_size))
    codes = []
    for ykm in range(y0, y1 + 1):
        for xkm in range(x0, x1 + 1):
            codes.append((f"33{xkm:03d}-{ykm:04d}", xkm, ykm))
    return codes


def _extract_rasters_from_zip(zip_path, extract_dir, log=None):
    os.makedirs(extract_dir, exist_ok=True)
    rasters = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            low = member.lower()
            if low.endswith((".tif", ".tiff")) and not member.endswith("/"):
                zf.extract(member, extract_dir)
                rasters.append(os.path.join(extract_dir, member))
    if not rasters:
        raise RuntimeError(f"ZIP contains no GeoTIFF: {zip_path}")
    if log:
        log(f"Extracted {len(rasters)} raster(s) from {os.path.basename(zip_path)}")
    return rasters


def _ensure_singleband_float(path, nodata=-9999, log=None):
    if gdal is None:
        return path
    try:
        ds = gdal.Open(path, gdal.GA_Update)
        if not ds:
            return path
        if ds.RasterCount != 1:
            raise RuntimeError(
                f"Downloaded raster has {ds.RasterCount} bands. This looks like a rendered RGB product, not a numeric height grid: {path}"
            )
        band = ds.GetRasterBand(1)
        if band:
            band.SetNoDataValue(nodata)
        ds = None
    except RuntimeError:
        raise
    except Exception as e:
        if log:
            log(f"Could not normalize raster metadata for {path}: {e}")
    return path



def _download_bayern_opendata_tiles(product, extent, source_crs, target_folder, log=None, is_canceled=None):
    cfg = _provider_config("Bayern")
    product_upper = product.upper()
    if product_upper not in cfg.get("products", {}):
        raise RuntimeError(
            f"Unsupported Bayern product: {product}. Available products: "
            + ", ".join(sorted(cfg.get("products", {}).keys()))
        )

    target_authid = cfg.get("target_authid", "EPSG:25832")
    extent_target = transform_extent(extent, source_crs, target_authid)
    tile_size = int(cfg.get("tile_size", 1000))
    max_workers = int(cfg.get("max_workers", 6))
    product_cfg = cfg["products"][product_upper]

    if log:
        log(f"Bayern OpenData product: {product_upper}")
        log(f"Provider/native CRS: {target_authid}")
        log(f"Request extent in {target_authid}: {extent_target.toString()}")
        log("Using Bayerische Vermessungsverwaltung OpenData 1 km GeoTIFF tiles.")
        if product_upper == "DOM20":
            log("Bayern DOM20 filename pattern: 32<east_km>_<north_km>_20_DOM.tif, e.g. 32676_5479_20_DOM.tif")

    tile_names = _bayern_tile_names(extent_target, tile_size=tile_size)
    if not tile_names:
        raise RuntimeError("No Bayern tile intersects the requested extent.")

    metalink_urls = {}
    if not product_cfg.get("skip_metalink", False):
        try:
            metalink_urls = _parse_bayern_metalink(product_cfg, log=log)
        except Exception as e:
            if log:
                log(f"Could not read Bayern Metalink. Falling back to direct URL templates: {e}")
    elif log:
        log(f"Bayern {product_upper}: Metalink lookup skipped; using direct URL template(s).")

    if log:
        log(f"Intersecting Bayern 1 km tiles: {len(tile_names)}")
        log("Download strategy: parallel GeoTIFF download first, then post-processing/merge.")
        log(f"Parallel download workers: {min(max_workers, len(tile_names))}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(target_folder, f"bayern_{product_upper.lower()}_tiles_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    jobs = []
    for idx, name in enumerate(tile_names, start=1):
        urls = []
        for n in _name_variants_bayern(name, product_upper):
            for u in metalink_urls.get(n, []):
                if u not in urls:
                    urls.append(u)
        for tmpl in product_cfg.get("direct_url_templates", []):
            for n in _name_variants_bayern(name, product_upper):
                url = tmpl.format(name=n)
                if url not in urls:
                    urls.append(url)
        jobs.append({
            "idx": idx,
            "name": name,
            "urls": urls,
            "out_path": os.path.join(out_dir, name),
        })

    downloaded = []
    missing = []

    def _download_job(job):
        if is_canceled and is_canceled():
            raise RuntimeError("Canceled")
        last_error = None
        last_url = None
        for url in job["urls"]:
            last_url = url
            try:
                return job, _download_bayern_raster_candidate(url, job["out_path"], log=None)
            except Exception as e:
                last_error = e
        if last_error:
            return_msg = f"{last_error}; candidates tested: {len(job['urls'])}; last URL: {last_url}"
        else:
            return_msg = "No URL candidates for tile"
        raise RuntimeError(return_msg)

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs)))) as executor:
        future_map = {executor.submit(_download_job, job): job for job in jobs}
        completed = 0
        for future in as_completed(future_map):
            job = future_map[future]
            if is_canceled and is_canceled():
                raise RuntimeError("Canceled")
            completed += 1
            try:
                _job, path = future.result()
                _ensure_singleband_float(path, nodata=cfg.get("nodata", -9999), log=log)
                downloaded.append(path)
                if log:
                    log(f"Downloaded Bayern tile {completed}/{len(jobs)}: {job['name']}")
            except Exception as e:
                missing.append((job["name"], str(e)))
                if log:
                    log(f"Bayern tile not available or failed {completed}/{len(jobs)}: {job['name']} | {e}")

    if not downloaded:
        detail = "\n".join(f"{n}: {m}" for n, m in missing[:10])
        raise RuntimeError("No Bayern OpenData GeoTIFF tiles could be downloaded. Last messages:\n" + detail)
    if missing and log:
        log(f"Warning: {len(missing)} requested Bayern tile(s) were unavailable/failed. Continuing with downloaded tiles.")
    if log:
        log(f"Downloaded Bayern raster tiles: {len(downloaded)}")
    return downloaded[0] if len(downloaded) == 1 else downloaded

def _download_brandenburg_opendata_tiles(product, extent, source_crs, target_folder, log=None, is_canceled=None):
    cfg = _provider_config("Brandenburg")
    product_upper = product.upper()
    target_authid = cfg.get("target_authid", "EPSG:25833")
    extent_target = transform_extent(extent, source_crs, target_authid)
    base_url = cfg["base_urls"][product_upper]
    file_prefix = cfg["file_prefix"][product_upper]
    tile_size = int(cfg.get("tile_size", 1000))
    max_workers = int(cfg.get("max_workers", 6))

    if log:
        log(f"Brandenburg OpenData product: {product_upper}")
        log(f"Provider/native CRS: {target_authid}")
        log(f"Request extent in {target_authid}: {extent_target.toString()}")
        log("Using direct LGB OpenData ZIP tiles instead of the rendered RGB WCS.")

    tiles = _brandenburg_tile_codes(extent_target, tile_size=tile_size)
    if not tiles:
        raise RuntimeError("No Brandenburg tile intersects the requested extent.")
    if log:
        log(f"Intersecting Brandenburg 1 km tiles: {len(tiles)}")
        log("Download strategy: parallel ZIP download first, then extract all ZIPs, then post-processing/merge.")
        log(f"Parallel download workers: {min(max_workers, len(tiles))}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    zip_dir = os.path.join(target_folder, f"brandenburg_{product_upper.lower()}_zips_{stamp}")
    extract_dir = os.path.join(target_folder, f"brandenburg_{product_upper.lower()}_tiles_{stamp}")
    os.makedirs(zip_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)

    jobs = []
    for idx, (code, _xkm, _ykm) in enumerate(tiles, start=1):
        name = f"{file_prefix}_{code}.zip"
        jobs.append({
            "idx": idx,
            "name": name,
            "url": base_url + name,
            "zip_path": os.path.join(zip_dir, name),
        })

    downloaded = []
    missing = []

    def _download_job(job):
        if is_canceled and is_canceled():
            raise RuntimeError("Canceled")
        return job, _download_file(job["url"], job["zip_path"], log=None)

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs)))) as executor:
        future_map = {executor.submit(_download_job, job): job for job in jobs}
        completed = 0
        for future in as_completed(future_map):
            job = future_map[future]
            if is_canceled and is_canceled():
                raise RuntimeError("Canceled")
            completed += 1
            try:
                _job, zip_path = future.result()
                downloaded.append(zip_path)
                if log:
                    log(f"Downloaded ZIP {completed}/{len(jobs)}: {job['name']}")
            except Exception as e:
                missing.append((job["name"], str(e)))
                if log:
                    log(f"Tile not available or failed {completed}/{len(jobs)}: {job['name']} | {e}")

    if not downloaded:
        detail = "\n".join(f"{n}: {m}" for n, m in missing[:10])
        raise RuntimeError("No Brandenburg OpenData ZIP tiles could be downloaded. Last messages:\n" + detail)

    if log:
        log(f"Downloaded ZIP tiles: {len(downloaded)}")
        log("Extracting downloaded ZIP tiles...")

    out_rasters = []
    for idx, zip_path in enumerate(sorted(downloaded), start=1):
        if is_canceled and is_canceled():
            raise RuntimeError("Canceled")
        try:
            if log:
                log(f"Extracting ZIP {idx}/{len(downloaded)}: {os.path.basename(zip_path)}")
            rasters = _extract_rasters_from_zip(zip_path, extract_dir, log=None)
            for rp in rasters:
                _ensure_singleband_float(rp, nodata=cfg.get("nodata", -9999), log=log)
            out_rasters.extend(rasters)
        except Exception as e:
            missing.append((os.path.basename(zip_path), str(e)))
            if log:
                log(f"Extraction/validation failed: {os.path.basename(zip_path)} | {e}")

    if not out_rasters:
        detail = "\n".join(f"{n}: {m}" for n, m in missing[:10])
        raise RuntimeError("No Brandenburg OpenData rasters could be extracted. Last messages:\n" + detail)
    if missing and log:
        log(f"Warning: {len(missing)} requested Brandenburg tile(s) were unavailable/failed. Continuing with downloaded/extracted tiles.")
    if log:
        log(f"Extracted raster tiles: {len(out_rasters)}")
    return out_rasters[0] if len(out_rasters) == 1 else out_rasters
def download_wcs_geotiff(product, extent, source_crs, target_folder, log=None, is_canceled=None, provider="Sachsen-Anhalt"):
    """Download DGM/DOM rasters. Direct OpenData providers bypass WCS where needed."""
    if provider == "Bayern":
        return _download_bayern_opendata_tiles(
            product=product,
            extent=extent,
            source_crs=source_crs,
            target_folder=target_folder,
            log=log,
            is_canceled=is_canceled,
        )
    if provider == "Brandenburg":
        return _download_brandenburg_opendata_tiles(
            product=product,
            extent=extent,
            source_crs=source_crs,
            target_folder=target_folder,
            log=log,
            is_canceled=is_canceled,
        )

    if is_canceled and is_canceled():
        raise RuntimeError("Canceled")

    os.makedirs(target_folder, exist_ok=True)
    product_upper = product.upper()
    target_authid = provider_target_authid(provider)
    extent_target = transform_extent(extent, source_crs, target_authid)

    if log:
        log(f"{provider} WCS product: {product_upper}")
        log(f"Provider/request CRS: {target_authid}")
        log(f"Request extent in {target_authid}: {extent_target.toString()}")

    service_urls = _service_urls(product_upper, provider=provider)
    last_error = None
    for service_index, base_url in enumerate(service_urls, start=1):
        try:
            if log:
                log(f"WCS base URL {service_index}/{len(service_urls)}: {base_url}")
            ids = get_coverage_ids_for_url(base_url, log=log)
            coverage_id = choose_coverage_id(product_upper, ids, base_url=base_url)
            if log:
                log(f"Using coverage id: {coverage_id}")

            tiles = _split_extent(extent_target, max_edge_m=800.0)
            if log:
                if len(tiles) == 1:
                    log("WCS request is small enough for one GeoTIFF tile.")
                else:
                    log(f"Large WCS request detected. Splitting into {len(tiles)} tiles of max. about 800 x 800 m.")

            stamp = time.strftime("%Y%m%d_%H%M%S")
            prefix = "bb" if provider == "Brandenburg" else "st"
            out_paths = []

            # Parallel WCS tile stage. There is no ZIP extraction for WCS,
            # but the task still returns all downloaded GeoTIFFs first so the
            # dialog can merge/clip/reproject once at the end.
            max_workers = min(6, max(1, len(tiles)))
            if log:
                log(f"Download strategy: parallel WCS tile download first, then post-processing/merge.")
                log(f"Parallel WCS workers: {max_workers}")

            def _download_wcs_job(item):
                tile_index, tile_extent = item
                if is_canceled and is_canceled():
                    raise RuntimeError("Canceled")
                out_path = os.path.join(target_folder, f"{prefix}_{product_upper.lower()}_wcs_{stamp}_tile_{tile_index:04d}.tif")
                _download_single_wcs_tile(
                    base_url=base_url,
                    coverage_id=coverage_id,
                    tile_extent_target=tile_extent,
                    out_path=out_path,
                    log=None,
                    is_canceled=is_canceled,
                    tile_label=f"Tile {tile_index}/{len(tiles)}",
                    target_authid=target_authid,
                )
                return tile_index, out_path

            tile_items = list(enumerate(tiles, start=1))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(_download_wcs_job, item): item for item in tile_items}
                completed = 0
                for future in as_completed(future_map):
                    if is_canceled and is_canceled():
                        raise RuntimeError("Canceled")
                    tile_index, tile_extent = future_map[future]
                    completed += 1
                    tile_index_done, out_path = future.result()
                    out_paths.append((tile_index_done, out_path))
                    if log:
                        log(f"Downloaded WCS tile {completed}/{len(tiles)}: {os.path.basename(out_path)}")

            out_paths = [p for _idx, p in sorted(out_paths, key=lambda item: item[0])]
            return out_paths[0] if len(out_paths) == 1 else out_paths
        except Exception as e:
            last_error = e
            if log:
                log(f"WCS base URL failed: {e}")
                log(f"Trying next {provider} WCS endpoint if available...")

    raise RuntimeError(f"All {provider} WCS endpoints failed. Last error: {last_error}")

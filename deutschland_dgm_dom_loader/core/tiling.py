import math

from qgis.core import (
    QgsCoordinateTransform,
    QgsProject,
    QgsCoordinateReferenceSystem
)

from .config import TARGET_CRS_AUTHID, TILE_SIZE_METERS


def transform_extent_to_target(extent, source_crs):
    target_crs = QgsCoordinateReferenceSystem(TARGET_CRS_AUTHID)

    if source_crs == target_crs:
        return extent

    transform = QgsCoordinateTransform(
        source_crs,
        target_crs,
        QgsProject.instance()
    )
    return transform.transformBoundingBox(extent)


def extent_to_tile_origins(extent, source_crs):
    extent_25833 = transform_extent_to_target(extent, source_crs)

    xmin = extent_25833.xMinimum()
    ymin = extent_25833.yMinimum()
    xmax = extent_25833.xMaximum()
    ymax = extent_25833.yMaximum()

    tile_size = TILE_SIZE_METERS

    col_min = math.floor(xmin / tile_size)
    col_max = math.floor((xmax - 1e-9) / tile_size)
    row_min = math.floor(ymin / tile_size)
    row_max = math.floor((ymax - 1e-9) / tile_size)

    origins = []
    for col in range(col_min, col_max + 1):
        for row in range(row_min, row_max + 1):
            x0 = col * tile_size
            y0 = row * tile_size
            origins.append((x0, y0))

    return origins


def tile_origin_to_codes(x0: int, y0: int):
    """
    Convert tile lower-left origin in EPSG:25833 meters
    to GeoSN filename codes.

    Example:
    324000 -> 33324
    5688000 -> 5688
    """
    x_km = int(x0 // 1000)
    y_km = int(y0 // 1000)

    x_code = f"33{x_km:03d}"
    y_code = f"{y_km:04d}"
    return x_code, y_code


def extent_to_geosn_filenames(extent, source_crs, product: str):
    product = product.lower()
    origins = extent_to_tile_origins(extent, source_crs)

    filenames = []
    for x0, y0 in origins:
        x_code, y_code = tile_origin_to_codes(x0, y0)
        filename = f"{product}_{x_code}_{y_code}_2_sn_tiff.zip"
        filenames.append(filename)

    return sorted(filenames)
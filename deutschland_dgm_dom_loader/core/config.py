PLUGIN_NAME = "Sachsen DGM Loader"
TARGET_CRS_AUTHID = "EPSG:25833"
TILE_SIZE_METERS = 2000

SUPPORTED_PRODUCTS = {
    "DGM1": {"label": "Digital Terrain Model 1 m"},
    "DOM1": {"label": "Digital Surface Model 1 m"},
}

VALID_RASTER_EXTENSIONS = (".tif", ".tiff")
VALID_ARCHIVE_EXTENSIONS = (".zip",)
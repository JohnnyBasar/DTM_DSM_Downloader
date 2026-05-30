PLUGIN_NAME = "Sachsen DGM Loader"
TARGET_CRS_AUTHID = "EPSG:25833"
TILE_SIZE_METERS = 2000

SUPPORTED_PRODUCTS = {
    "DGM1": {"label": "Digital Terrain Model 1 m"},
    "DOM1": {"label": "Digital Surface Model 1 m"},
    "DOM20": {"label": "Digital Surface Model 20 cm"},
}

# Product availability is provider-specific. Keep this central so the GUI can
# adapt the product dropdown and future products such as DOP can be added
# without changing the UI logic.
STATE_PRODUCTS = {
    "Sachsen": ["DGM1", "DOM1"],
    "Sachsen-Anhalt": ["DGM1", "DOM1"],
    "Brandenburg": ["DGM1", "DOM1"],
    "Bayern": ["DGM1", "DOM20"],
}


def products_for_state(state: str) -> list[str]:
    return list(STATE_PRODUCTS.get(state, []))

VALID_RASTER_EXTENSIONS = (".tif", ".tiff")
VALID_ARCHIVE_EXTENSIONS = (".zip",)
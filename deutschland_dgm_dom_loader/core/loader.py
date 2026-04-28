import os
from qgis.core import QgsRasterLayer, QgsProject


def load_raster(path: str, name: str | None = None):
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]

    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        raise RuntimeError(f"Raster could not be loaded: {path}")

    QgsProject.instance().addMapLayer(layer)
    return layer
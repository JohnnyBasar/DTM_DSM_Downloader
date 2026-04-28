import os
import zipfile

from .config import VALID_RASTER_EXTENSIONS


def extract_zip(zip_path: str, output_folder: str, log=None) -> str:
    os.makedirs(output_folder, exist_ok=True)

    if log:
        log(f"Extracting: {zip_path}")
        log(f"Extract to: {output_folder}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(output_folder)

    return output_folder


def find_rasters(folder: str) -> list[str]:
    rasters = []
    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(VALID_RASTER_EXTENSIONS):
                rasters.append(os.path.join(root, name))
    return sorted(rasters)
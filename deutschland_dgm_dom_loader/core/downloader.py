import os
import urllib.request
from urllib.parse import urlparse


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = os.path.basename(path)
    return name or "download.zip"


def download_file(url: str, output_folder: str, log=None, progress_callback=None, is_canceled_callback=None) -> str:
    os.makedirs(output_folder, exist_ok=True)

    log = log or (lambda msg: None)
    progress_callback = progress_callback or (lambda frac: None)
    is_canceled_callback = is_canceled_callback or (lambda: False)

    filename = filename_from_url(url)
    output_path = os.path.join(output_folder, filename)

    log(f"Downloading: {url}")
    log(f"Target file: {output_path}")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "QGIS Sachsen DGM Loader/0.1.3"
        }
    )

    chunk_size = 1024 * 1024

    with urllib.request.urlopen(request) as response, open(output_path, "wb") as fh:
        total_size = response.headers.get("Content-Length")
        total_size = int(total_size) if total_size else None
        downloaded = 0

        while True:
            if is_canceled_callback():
                raise RuntimeError("Download canceled by user.")

            chunk = response.read(chunk_size)
            if not chunk:
                break

            fh.write(chunk)
            downloaded += len(chunk)

            if total_size and total_size > 0:
                progress_callback(downloaded / total_size)

    progress_callback(1.0)
    return output_path
import os
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core.links import extract_links_from_text, filter_links_by_product
from ..core.downloader import download_file
from ..core.extractor import extract_zip, find_rasters


class GeoSNBatchProvider:
    def __init__(self, log=None, progress_callback=None, is_canceled_callback=None):
        self.log = log or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda value: None)
        self.is_canceled_callback = is_canceled_callback or (lambda: False)

        self.last_missing_urls = []
        self.last_existing_urls = []

    def _check_canceled(self):
        if self.is_canceled_callback():
            raise RuntimeError("Operation canceled by user.")

    def process_links(self, links_text: str, product: str, target_folder: str) -> list[str]:
        links = extract_links_from_text(links_text)
        if not links:
            raise ValueError("No valid http(s) download links were found.")

        links = filter_links_by_product(links, product)
        return self.process_url_list(links=links, target_folder=target_folder)

    def process_url_list(self, links: list[str], target_folder: str) -> list[str]:
        """Download all GeoSN ZIPs first, then extract all archives.

        This is intentionally a two-stage pipeline:
        1) parallel ZIP downloads
        2) archive extraction + raster discovery

        The final merge/clip/reprojection remains handled by the dialog after
        this task returns the list of extracted raster files.
        """
        if not links:
            raise ValueError("No download URLs were provided.")

        self.log(f"Received {len(links)} URL(s).")
        self.log("Download strategy: parallel download first, then extract all archives, then post-processing/merge.")

        self.last_existing_urls = []
        self.last_missing_urls = []
        all_rasters = []

        downloads_dir = os.path.join(target_folder, "downloads")
        extract_dir = os.path.join(target_folder, "extracted")
        os.makedirs(downloads_dir, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)

        total_links = len(links)
        max_workers = min(6, max(1, total_links))
        self.log(f"Parallel download workers: {max_workers}")

        downloaded_archives = []

        def _download_one(idx_url):
            idx, url = idx_url
            self._check_canceled()
            zip_path = download_file(
                url=url,
                output_folder=downloads_dir,
                log=None,
                progress_callback=None,
                is_canceled_callback=self.is_canceled_callback,
            )
            return idx, url, zip_path

        # Stage 1: download all archives first.
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_download_one, item): item for item in enumerate(links, start=1)}
            completed = 0
            for future in as_completed(future_map):
                self._check_canceled()
                idx, url = future_map[future]
                completed += 1
                try:
                    _idx, _url, zip_path = future.result()
                    downloaded_archives.append((_idx, _url, zip_path))
                    self.last_existing_urls.append(_url)
                    self.log(f"Downloaded ZIP {completed}/{total_links}: {os.path.basename(zip_path)}")
                except urllib.error.HTTPError as e:
                    self.last_missing_urls.append(url)
                    self.log(f"HTTP error {e.code} for URL: {url}")
                except urllib.error.URLError as e:
                    self.last_missing_urls.append(url)
                    self.log(f"URL error for {url}: {e}")
                except Exception as e:
                    msg = str(e).lower()
                    if "cancel" in msg:
                        raise
                    self.last_missing_urls.append(url)
                    self.log(f"Unexpected download error for {url}: {e}")
                self.progress_callback(70.0 * completed / total_links)

        if not downloaded_archives:
            raise ValueError("None of the generated download URLs could be downloaded.")

        self.log(f"Downloaded archives: {len(downloaded_archives)}")
        self.log("Extracting downloaded archives...")

        # Stage 2: extract all archives and collect rasters.
        downloaded_archives.sort(key=lambda item: item[0])
        total_archives = len(downloaded_archives)
        for extract_idx, (_idx, url, zip_path) in enumerate(downloaded_archives, start=1):
            self._check_canceled()
            stem = os.path.splitext(os.path.basename(zip_path))[0]
            this_extract_dir = os.path.join(extract_dir, stem)
            try:
                self.log(f"Extracting archive {extract_idx}/{total_archives}: {os.path.basename(zip_path)}")
                extract_zip(zip_path, this_extract_dir, log=None)
                rasters = find_rasters(this_extract_dir)
                if not rasters:
                    self.log(f"No raster found in archive: {zip_path}")
                for raster in rasters:
                    self.log(f"Raster found: {raster}")
                    all_rasters.append(raster)
            except Exception as e:
                self.log(f"Could not extract archive {zip_path}: {e}")
            self.progress_callback(70.0 + 30.0 * extract_idx / total_archives)

        self.log(
            f"Processing finished: {len(self.last_existing_urls)} successful download(s), "
            f"{len(self.last_missing_urls)} skipped/failed URL(s), "
            f"{len(all_rasters)} raster file(s) found."
        )

        if not all_rasters:
            raise ValueError("Downloads completed, but no raster files were found in the archives.")

        return all_rasters

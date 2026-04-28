import traceback

from qgis.core import QgsTask

from ..core.links import (
    extract_base_url_from_seed_link,
    join_base_and_filenames,
    validate_seed_link_product
)
from ..core.tiling import extent_to_geosn_filenames
from ..providers.geosn_batch_provider import GeoSNBatchProvider
from .signals import TaskSignals


class GeoSNExtentDownloadTask(QgsTask):
    def __init__(self, description: str, extent, source_crs, product: str, seed_link: str, target_folder: str):
        super().__init__(description, QgsTask.CanCancel)

        self.extent = extent
        self.source_crs = source_crs
        self.product = product
        self.seed_link = seed_link
        self.target_folder = target_folder

        self.signals = TaskSignals()

        self.result_rasters = []
        self.error_message = None
        self.error_traceback = None
        self.was_canceled = False
        self.generated_urls = []
        self.missing_urls = []
        self.existing_urls = []

    def _log(self, msg: str):
        self.signals.log_message.emit(str(msg))

    def _progress(self, value: float):
        value = max(0.0, min(100.0, float(value)))
        self.signals.progress_value.emit(value)
        self.setProgress(value)

    def run(self):
        try:
            self._log("Background extent task started.")

            validate_seed_link_product(self.seed_link, self.product)
            self._log(f"Seed link matches selected product: {self.product}")

            filenames = extent_to_geosn_filenames(
                extent=self.extent,
                source_crs=self.source_crs,
                product=self.product
            )

            self._log(f"Derived {len(filenames)} filename(s) from current extent.")
            for name in filenames:
                self._log(f"  - {name}")

            base_url = extract_base_url_from_seed_link(self.seed_link)
            self._log(f"Derived base URL: {base_url}")

            self.generated_urls = join_base_and_filenames(base_url, filenames)

            provider = GeoSNBatchProvider(
                log=self._log,
                progress_callback=self._progress,
                is_canceled_callback=self.isCanceled
            )

            self.result_rasters = provider.process_url_list(
                links=self.generated_urls,
                target_folder=self.target_folder
            )

            self.existing_urls = provider.last_existing_urls
            self.missing_urls = provider.last_missing_urls

            if self.isCanceled():
                self.was_canceled = True
                self._log("Task was canceled.")
                return False

            self._progress(100.0)
            self._log(
                f"Background extent task finished. "
                f"Generated: {len(self.generated_urls)}, "
                f"existing: {len(self.existing_urls)}, "
                f"missing: {len(self.missing_urls)}, "
                f"rasters: {len(self.result_rasters)}."
            )
            return True

        except RuntimeError as e:
            msg = str(e).lower()
            if "cancel" in msg:
                self.was_canceled = True
                self._log("Task canceled by user.")
                return False

            self.error_message = str(e)
            self.error_traceback = traceback.format_exc()
            self._log(f"ERROR: {self.error_message}")
            self._log(self.error_traceback)
            return False

        except Exception as e:
            self.error_message = str(e)
            self.error_traceback = traceback.format_exc()
            self._log(f"ERROR: {self.error_message}")
            self._log(self.error_traceback)
            return False
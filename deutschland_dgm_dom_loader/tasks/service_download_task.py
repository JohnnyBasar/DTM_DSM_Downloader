import traceback

from qgis.core import QgsTask

from ..core.geosn_service import query_tiles_for_extent
from ..providers.geosn_batch_provider import GeoSNBatchProvider
from .signals import TaskSignals


class GeoSNServiceDownloadTask(QgsTask):
    def __init__(self, description: str, extent, source_crs, product: str, target_folder: str):
        super().__init__(description, QgsTask.CanCancel)

        self.extent = extent
        self.source_crs = source_crs
        self.product = product
        self.target_folder = target_folder

        self.signals = TaskSignals()

        self.result_rasters = []
        self.result_features = []
        self.download_urls = []
        self.error_message = None
        self.error_traceback = None
        self.was_canceled = False
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
            self._progress(5.0)
            self._log(f"Querying official GeoSN service for product: {self.product}")

            self.result_features = query_tiles_for_extent(
                extent=self.extent,
                source_crs=self.source_crs,
                product=self.product
            )

            if self.isCanceled():
                self.was_canceled = True
                self._log("Task canceled.")
                return False

            self._log(f"GeoSN service returned {len(self.result_features)} feature(s).")

            self.download_urls = []
            for idx, item in enumerate(self.result_features, start=1):
                url = item.get("download")
                self._log(
                    f"[{idx}] Kachel={item.get('kachel')} | "
                    f"Download={url} | "
                    f"Stand={item.get('stand')}"
                )
                if url:
                    self.download_urls.append(url)

            if not self.download_urls:
                raise ValueError("Official GeoSN service returned no usable download URLs.")

            self._progress(15.0)
            self._log(f"Starting download of {len(self.download_urls)} URL(s) from official service...")

            provider = GeoSNBatchProvider(
                log=self._log,
                progress_callback=lambda v: self._progress(15.0 + v * 0.85),
                is_canceled_callback=self.isCanceled
            )

            self.result_rasters = provider.process_url_list(
                links=self.download_urls,
                target_folder=self.target_folder
            )

            self.existing_urls = provider.last_existing_urls
            self.missing_urls = provider.last_missing_urls

            if self.isCanceled():
                self.was_canceled = True
                self._log("Task canceled.")
                return False

            self._progress(100.0)
            self._log(
                f"Official GeoSN download task finished. "
                f"Features: {len(self.result_features)}, "
                f"download URLs: {len(self.download_urls)}, "
                f"successful downloads: {len(self.existing_urls)}, "
                f"failed URLs: {len(self.missing_urls)}, "
                f"rasters: {len(self.result_rasters)}."
            )
            return True

        except Exception as e:
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
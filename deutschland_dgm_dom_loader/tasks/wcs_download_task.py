import traceback

from qgis.core import QgsTask

from ..core.wcs_service import download_wcs_geotiff
from .signals import TaskSignals


class WCSDownloadTask(QgsTask):
    def __init__(self, description: str, extent, source_crs, product: str, target_folder: str, provider: str = "Sachsen-Anhalt"):
        super().__init__(description, QgsTask.CanCancel)
        self.extent = extent
        self.source_crs = source_crs
        self.product = product
        self.target_folder = target_folder
        self.provider = provider
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
            self._progress(5)
            self._log(f"Starting {self.provider} WCS download...")
            path = download_wcs_geotiff(
                product=self.product,
                extent=self.extent,
                source_crs=self.source_crs,
                target_folder=self.target_folder,
                log=self._log,
                provider=self.provider,
                is_canceled=self.isCanceled,
            )
            if self.isCanceled():
                self.was_canceled = True
                self._log("Task canceled.")
                return False
            if isinstance(path, (list, tuple)):
                self.result_rasters = list(path)
                self.existing_urls = list(path)
            else:
                self.result_rasters = [path]
                self.existing_urls = [path]
            self._progress(100)
            self._log(f"{self.provider} WCS download task finished.")
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

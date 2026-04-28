import traceback

from qgis.core import QgsTask

from ..providers.geosn_batch_provider import GeoSNBatchProvider
from .signals import TaskSignals


class GeoSNDownloadTask(QgsTask):
    def __init__(self, description: str, links_text: str, product: str, target_folder: str):
        super().__init__(description, QgsTask.CanCancel)

        self.links_text = links_text
        self.product = product
        self.target_folder = target_folder

        self.signals = TaskSignals()

        self.result_rasters = []
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
            self._log("Background task started.")

            provider = GeoSNBatchProvider(
                log=self._log,
                progress_callback=self._progress,
                is_canceled_callback=self.isCanceled
            )

            self.result_rasters = provider.process_links(
                links_text=self.links_text,
                product=self.product,
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
                f"Background task finished. "
                f"Existing: {len(self.existing_urls)}, "
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
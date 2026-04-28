import traceback

from qgis.core import QgsTask

from ..core.geosn_service import query_tiles_for_extent
from .signals import TaskSignals


class GeoSNServiceQueryTask(QgsTask):
    def __init__(self, description: str, extent, source_crs, product: str):
        super().__init__(description, QgsTask.CanCancel)

        self.extent = extent
        self.source_crs = source_crs
        self.product = product

        self.signals = TaskSignals()

        self.result_features = []
        self.error_message = None
        self.error_traceback = None
        self.was_canceled = False

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

            self._progress(100.0)
            self._log(f"GeoSN service returned {len(self.result_features)} feature(s).")

            for idx, item in enumerate(self.result_features, start=1):
                self._log(
                    f"[{idx}] Kachel={item.get('kachel')} | "
                    f"Download={item.get('download')} | "
                    f"Stand={item.get('stand')}"
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
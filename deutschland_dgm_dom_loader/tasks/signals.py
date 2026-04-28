from qgis.PyQt.QtCore import QObject, pyqtSignal


class TaskSignals(QObject):
    log_message = pyqtSignal(str)
    progress_value = pyqtSignal(float)
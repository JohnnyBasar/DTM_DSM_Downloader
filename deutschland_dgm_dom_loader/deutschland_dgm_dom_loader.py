import os

from qgis.PyQt.QtWidgets import QAction, QDockWidget, QScrollArea, QFrame
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt

from .gui.main_dialog import GermanyDEMDOMDialog


def _qt_enum(namespace_name, attr_name):
    namespace = getattr(Qt, namespace_name, None)
    if namespace is not None and hasattr(namespace, attr_name):
        return getattr(namespace, attr_name)
    return getattr(Qt, attr_name)


class GermanyDEMDOMDownloaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None
        self.dock_widget = None
        self.scroll_area = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon_path), "Germany DEM/DSM Downloader", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Germany DEM/DSM Downloader", self.action)

    def unload(self):
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Germany DEM/DSM Downloader", self.action)

        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None
            self.scroll_area = None
            self.dialog = None

    def _create_dock_widget(self):
        self.dialog = GermanyDEMDOMDialog(self.iface)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        frame_shape = QFrame.Shape.NoFrame if hasattr(QFrame, "Shape") else QFrame.NoFrame
        self.scroll_area.setFrameShape(frame_shape)
        self.scroll_area.setWidget(self.dialog)

        self.dock_widget = QDockWidget("Germany DEM/DSM Downloader", self.iface.mainWindow())
        self.dock_widget.setObjectName("GermanyDEMDOMDownloaderDockWidget")
        left_area = _qt_enum("DockWidgetArea", "LeftDockWidgetArea")
        right_area = _qt_enum("DockWidgetArea", "RightDockWidgetArea")
        self.dock_widget.setAllowedAreas(left_area | right_area)
        self.dock_widget.setWidget(self.scroll_area)
        self.dock_widget.setMinimumWidth(420)

        self.iface.addDockWidget(right_area, self.dock_widget)

    def run(self):
        if self.dock_widget is None:
            self._create_dock_widget()
        self.dock_widget.show()
        self.dock_widget.raise_()

from qgis.gui import QgsExtentWidget
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapLayerType,
    QgsWkbTypes,
)
import processing
import os

from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QTextEdit,
    QMessageBox,
    QProgressBar,
    QGroupBox,
    QFormLayout,
    QCheckBox,
)

from qgis.core import QgsApplication

from ..core.tiling import extent_to_geosn_filenames
from ..core.loader import load_raster
from ..tasks.service_query_task import GeoSNServiceQueryTask
from ..tasks.service_download_task import GeoSNServiceDownloadTask
from ..tasks.wcs_download_task import WCSDownloadTask
from ..core.wcs_service import get_coverage_ids, provider_target_authid
from ..core.config import products_for_state, SUPPORTED_PRODUCTS


class GermanyDEMDOMDialog(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.current_task = None

        self.setWindowTitle("Germany DEM/DSM Downloader")
        self.setMinimumWidth(390)

        self.cmb_state = QComboBox()
        self.cmb_state.addItems(["Sachsen", "Sachsen-Anhalt", "Brandenburg", "Bayern"])
        self.cmb_state.currentTextChanged.connect(self._update_product_options)

        self.cmb_product = QComboBox()
        self._update_product_options(self.cmb_state.currentText())

        self.txt_folder = QLineEdit()
        self.btn_browse = QPushButton("…")
        self.btn_browse.clicked.connect(self.select_folder)

        # Classic QGIS extent widget: field + "..." menu with canvas extent,
        # layer extent and draw-on-canvas options.
        self.extent_widget = QgsExtentWidget()
        self.extent_widget.setMapCanvas(self.iface.mapCanvas())
        self.extent_widget.setCurrentExtent(
            self.iface.mapCanvas().extent(),
            self.iface.mapCanvas().mapSettings().destinationCrs(),
        )
        self.extent_widget.setOutputCrs(self.iface.mapCanvas().mapSettings().destinationCrs())

        self.chk_merge = QCheckBox("Merge downloaded tiles into one GeoTIFF")
        self.chk_merge.setChecked(True)

        self.chk_clip = QCheckBox("Clip result to selected extent rectangle")
        self.chk_clip.setChecked(True)

        self.chk_clip_polygon = QCheckBox("Clip result to exact polygon shape")
        self.chk_clip_polygon.setChecked(False)
        self.chk_clip_polygon.toggled.connect(self._update_polygon_ui)

        self.cmb_polygon_layer = QComboBox()

        self.chk_reproject_to_project = QCheckBox("Reproject final raster to project CRS")
        self.chk_reproject_to_project.setChecked(True)
        self.chk_reproject_to_project.setToolTip(
            "Downloads stay in the official provider CRS first "
            "(Sachsen EPSG:25833, Sachsen-Anhalt EPSG:25832, Brandenburg EPSG:25833, Bayern EPSG:25832). "
            "Enable this to warp the final GeoTIFF to the current QGIS project CRS."
        )

        self.chk_load_result = QCheckBox("Load final result into QGIS")
        self.chk_load_result.setChecked(True)

        self.btn_use_extent = QPushButton("Preview tiles / request")
        self.btn_use_extent.clicked.connect(self.use_current_extent)

        self.btn_query_service = QPushButton("Inspect service")
        self.btn_query_service.clicked.connect(self.query_official_service)

        self.btn_download_service = QPushButton("Download")
        self.btn_download_service.clicked.connect(self.download_from_official_service)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_current_task)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Germany DEM/DSM Downloader")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        subtitle = QLabel("Download official DGM/DOM raster data by federal-state provider. The available products are adapted to the selected federal state.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        source_group = QGroupBox("1  Data source")
        source_form = QFormLayout()
        source_form.addRow("Federal state / provider:", self.cmb_state)
        source_form.addRow("Product:", self.cmb_product)
        source_group.setLayout(source_form)
        layout.addWidget(source_group)

        extent_group = QGroupBox("2  Area of interest")
        extent_layout = QVBoxLayout()
        extent_hint = QLabel("Use the QGIS extent menu (…) to take the map canvas extent, a layer extent, or draw an extent on the map.")
        extent_hint.setWordWrap(True)
        extent_hint.setStyleSheet("color: #666;")
        extent_layout.addWidget(extent_hint)
        extent_layout.addWidget(self.extent_widget)
        extent_group.setLayout(extent_layout)
        layout.addWidget(extent_group)

        output_group = QGroupBox("3  Output and post-processing")
        output_layout = QVBoxLayout()

        row_folder = QHBoxLayout()
        row_folder.addWidget(QLabel("Target folder:"))
        row_folder.addWidget(self.txt_folder)
        row_folder.addWidget(self.btn_browse)
        output_layout.addLayout(row_folder)

        crs_hint = QLabel("Downloads are requested in the official provider CRS: Sachsen = EPSG:25833, Sachsen-Anhalt = EPSG:25832, Brandenburg = EPSG:25833, Bayern = EPSG:25832.")
        crs_hint.setWordWrap(True)
        crs_hint.setStyleSheet("color: #666;")
        output_layout.addWidget(crs_hint)

        output_layout.addWidget(self.chk_merge)
        output_layout.addWidget(self.chk_clip)
        output_layout.addWidget(self.chk_clip_polygon)

        row_polygon = QHBoxLayout()
        row_polygon.addWidget(QLabel("Polygon mask layer:"))
        row_polygon.addWidget(self.cmb_polygon_layer)
        output_layout.addLayout(row_polygon)

        output_layout.addWidget(self.chk_reproject_to_project)
        output_layout.addWidget(self.chk_load_result)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        action_group = QGroupBox("4  Run")
        action_layout = QVBoxLayout()
        row_actions = QHBoxLayout()
        row_actions.addWidget(self.btn_use_extent)
        row_actions.addWidget(self.btn_query_service)
        row_actions.addStretch(1)
        row_actions.addWidget(self.btn_cancel)
        row_actions.addWidget(self.btn_download_service)
        action_layout.addLayout(row_actions)
        action_layout.addWidget(QLabel("Progress:"))
        action_layout.addWidget(self.progress_bar)
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)

        self.setLayout(layout)

    def _update_product_options(self, state=None):
        state = state or self.cmb_state.currentText()
        previous = self._selected_product() if hasattr(self, "cmb_product") else ""
        products = products_for_state(state)

        self.cmb_product.blockSignals(True)
        self.cmb_product.clear()
        for product in products:
            label = SUPPORTED_PRODUCTS.get(product, {}).get("label", product)
            self.cmb_product.addItem(f"{product} — {label}", product)

        if previous in products:
            self.cmb_product.setCurrentIndex(products.index(previous))
        elif self.cmb_product.count() > 0:
            self.cmb_product.setCurrentIndex(0)
        self.cmb_product.blockSignals(False)

    def _selected_product(self):
        return self.cmb_product.currentData() or self.cmb_product.currentText().split(" — ", 1)[0]

    def log(self, msg):
        self.log_output.append(str(msg))

    def set_progress(self, value: float):
        self.progress_bar.setValue(int(round(value)))

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select target folder")
        if folder:
            self.txt_folder.setText(folder)

    def use_current_extent(self):
        extent, crs = self.get_selected_extent_and_crs()
        product = self._selected_product()
        provider = self.cmb_state.currentText()

        self.log(f"Selected extent: {extent.toString()}")
        self.log(f"Selected CRS: {crs.authid()}")
        self.log(f"Selected provider: {provider}")
        self.log(f"Selected product: {product}")

        if provider in ("Sachsen-Anhalt", "Brandenburg", "Bayern"):
            self.log(f"Tile preview is only available for Sachsen/GeoSN. {provider} uses WCS/direct OpenData downloads instead.")
            return

        try:
            filenames = extent_to_geosn_filenames(extent, crs, product)
            self.log("Derived GeoSN filenames:")
            for name in filenames:
                self.log(f"  - {name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.log(f"ERROR: {e}")

    def query_official_service(self):
        if self.current_task is not None:
            QMessageBox.information(self, "Task running", "A task is already running.")
            return

        product = self._selected_product()
        provider = self.cmb_state.currentText()
        extent, crs = self.get_selected_extent_and_crs()

        self.progress_bar.setValue(0)
        self._set_ui_busy(True)

        if provider in ("Brandenburg", "Bayern"):
            self.log(f"{provider} uses direct OpenData tile downloads. No WCS capabilities are required.")
            self.progress_bar.setValue(100)
            QMessageBox.information(
                self,
                "Direct OpenData provider",
                f"{provider} uses direct OpenData tile downloads for the selected product."
            )
            self._set_ui_busy(False)
            return

        if provider == "Sachsen-Anhalt":
            self.log(f"Reading {provider} WCS capabilities...")
            try:
                ids = get_coverage_ids(product, log=self.log, provider=provider)
                self.progress_bar.setValue(100)
                QMessageBox.information(self, "WCS capabilities", "Found coverage id candidates:\n\n" + "\n".join(ids[:20]))
            except Exception as e:
                self.log(f"ERROR: {e}")
                QMessageBox.critical(self, "WCS capabilities failed", str(e))
            finally:
                self._set_ui_busy(False)
            return

        self.log("Submitting official GeoSN service query task...")

        task = GeoSNServiceQueryTask(
            description=f"Query official GeoSN service for {product}",
            extent=extent,
            source_crs=crs,
            product=product,
        )

        self._wire_task(task)
        QgsApplication.taskManager().addTask(task)

    def download_from_official_service(self):
        if self.current_task is not None:
            QMessageBox.information(self, "Task running", "A task is already running.")
            return

        target_folder = self.txt_folder.text().strip()
        product = self._selected_product()
        provider = self.cmb_state.currentText()

        if not target_folder:
            QMessageBox.warning(self, "Missing folder", "Please select a target folder.")
            return

        try:
            extent, crs = self.get_selected_extent_and_crs()
            if self.chk_clip_polygon.isChecked() and self.get_selected_polygon_layer() is None:
                raise ValueError("Exact polygon clipping is enabled, but no polygon layer is selected.")
        except Exception as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return

        self.progress_bar.setValue(0)
        self._set_ui_busy(True)

        if provider in ("Sachsen-Anhalt", "Brandenburg", "Bayern"):
            self.log(f"Submitting {provider} download task...")
            task = WCSDownloadTask(
                description=f"Download {product} from {provider}",
                extent=extent,
                source_crs=crs,
                product=product,
                target_folder=target_folder,
                provider=provider,
            )
        else:
            self.log("Submitting official GeoSN download task...")
            task = GeoSNServiceDownloadTask(
                description=f"Download {product} from official GeoSN service",
                extent=extent,
                source_crs=crs,
                product=product,
                target_folder=target_folder,
            )

        self._wire_task(task)
        QgsApplication.taskManager().addTask(task)

    def _wire_task(self, task):
        task.signals.log_message.connect(self.log)
        task.signals.progress_value.connect(self.set_progress)

        task.taskCompleted.connect(lambda: self._on_task_finished(task, success=True))
        task.taskTerminated.connect(lambda: self._on_task_finished(task, success=False))

        self.current_task = task

    def cancel_current_task(self):
        if self.current_task is not None:
            self.log("Cancel requested...")
            self.current_task.cancel()

    def _set_ui_busy(self, busy: bool):
        self.btn_use_extent.setEnabled(not busy)
        self.btn_query_service.setEnabled(not busy)
        self.btn_download_service.setEnabled(not busy)
        self.btn_browse.setEnabled(not busy)
        self.cmb_state.setEnabled(not busy)
        self.cmb_product.setEnabled(not busy)
        self.extent_widget.setEnabled(not busy)
        self.chk_merge.setEnabled(not busy)
        self.chk_clip.setEnabled(not busy)
        self.chk_clip_polygon.setEnabled(not busy)
        self.cmb_polygon_layer.setEnabled((not busy) and self.chk_clip_polygon.isChecked())
        self.chk_reproject_to_project.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _on_task_finished(self, task, success: bool):
        if task is not self.current_task:
            return

        self._set_ui_busy(False)
        self.current_task = None

        if getattr(task, "was_canceled", False):
            self.log("Task canceled.")
            self.progress_bar.setValue(0)
            QMessageBox.information(self, "Canceled", "The task was canceled.")
            return

        rasters = getattr(task, "result_rasters", []) or []
        existing_count = len(getattr(task, "existing_urls", []))
        missing_count = len(getattr(task, "missing_urls", []))

        if not rasters:
            self.log("Task finished, but no rasters were found.")
            QMessageBox.warning(
                self,
                "No rasters found",
                f"No GeoTIFF raster was found.\n\n"
                f"Existing URLs: {existing_count}\n"
                f"Missing URLs: {missing_count}",
            )
            return

        selected_extent, selected_crs = self.get_selected_extent_and_crs()
        polygon_layer = self.get_selected_polygon_layer() if self.chk_clip_polygon.isChecked() else None
        product = self._selected_product()
        provider = self.cmb_state.currentText()

        try:
            final_product = self.postprocess_rasters(
                rasters=rasters,
                selected_extent=selected_extent,
                selected_crs=selected_crs,
                product=product,
                polygon_layer=polygon_layer,
                provider=provider,
            )
        except Exception as e:
            self.log(f"Post-processing failed: {e}")
            QMessageBox.critical(self, "Post-processing failed", str(e))
            return

        loaded_count = 0
        errors = []

        if self.chk_load_result.isChecked():
            if isinstance(final_product, list):
                for path in final_product:
                    try:
                        load_raster(path)
                        loaded_count += 1
                    except Exception as e:
                        errors.append(f"{path}: {e}")
            else:
                try:
                    load_raster(final_product)
                    loaded_count += 1
                except Exception as e:
                    errors.append(f"{final_product}: {e}")

        self.log(f"Loaded {loaded_count} raster(s) into QGIS.")
        self.log(f"Summary: {existing_count} existing URL(s), {missing_count} missing URL(s).")

        if errors:
            self.log("Some rasters could not be loaded:")
            for err in errors:
                self.log(err)
            QMessageBox.warning(
                self,
                "Partial success",
                f"{loaded_count} raster(s) loaded.\n"
                f"Existing URLs: {existing_count}\n"
                f"Missing URLs: {missing_count}\n"
                f"Some rasters could not be added to QGIS.",
            )
        else:
            QMessageBox.information(
                self,
                "Download complete",
                f"Finished successfully.\n\n"
                f"Existing URLs: {existing_count}\n"
                f"Missing URLs: {missing_count}\n"
                f"Loaded result layer(s): {loaded_count}",
            )

    def refresh_layer_list(self):
        self.cmb_polygon_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() != QgsMapLayerType.VectorLayer:
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            self.cmb_polygon_layer.addItem(layer.name(), layer.id())

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_layer_list()
        self._update_polygon_ui()
        try:
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())
            self.extent_widget.setOutputCrs(self.iface.mapCanvas().mapSettings().destinationCrs())
        except Exception:
            pass

    def _update_polygon_ui(self):
        self.cmb_polygon_layer.setEnabled(self.chk_clip_polygon.isChecked())

    def get_selected_extent_and_crs(self):
        extent = self.extent_widget.outputExtent()
        crs = self.extent_widget.outputCrs()

        if extent is None or extent.isEmpty():
            raise ValueError("No valid extent selected.")
        if crs is None or not crs.isValid():
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        return extent, crs

    def get_selected_polygon_layer(self):
        layer_id = self.cmb_polygon_layer.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return None
        if layer.type() != QgsMapLayerType.VectorLayer:
            return None
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return None
        return layer

    def _transform_extent_to_target(self, extent, source_crs, target_authid):
        target_crs = QgsCoordinateReferenceSystem(target_authid)
        if source_crs == target_crs:
            return extent

        transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
        return transform.transformBoundingBox(extent)

    def _extent_to_processing_string(self, extent, crs_authid="EPSG:25833"):
        return f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{crs_authid}]"

    def _clip_by_extent(self, input_path, output_path, extent_str):
        processing.run("gdal:cliprasterbyextent", {
            "INPUT": input_path,
            "PROJWIN": extent_str,
            "OVERCRS": False,
            "NODATA": -99999,
            "OPTIONS": "",
            "DATA_TYPE": 6,
            "EXTRA": "",
            "OUTPUT": output_path,
        })
        return output_path

    def _clip_by_polygon(self, input_path, output_path, polygon_layer):
        params = {
            "INPUT": input_path,
            "MASK": polygon_layer,
            "SOURCE_CRS": None,
            "TARGET_CRS": None,
            "NODATA": -99999,
            "ALPHA_BAND": False,
            "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True,
            "SET_RESOLUTION": False,
            "X_RESOLUTION": None,
            "Y_RESOLUTION": None,
            "MULTITHREADING": True,
            "OPTIONS": "",
            "DATA_TYPE": 6,
            "EXTRA": "",
            "OUTPUT": output_path,
        }
        try:
            processing.run("gdal:cliprasterbymasklayer", params)
        except Exception:
            # Compatibility fallback for QGIS/GDAL builds with a smaller parameter set.
            minimal_params = {
                "INPUT": input_path,
                "MASK": polygon_layer,
                "NODATA": -99999,
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True,
                "KEEP_RESOLUTION": True,
                "OPTIONS": "",
                "DATA_TYPE": 6,
                "EXTRA": "",
                "OUTPUT": output_path,
            }
            processing.run("gdal:cliprasterbymasklayer", minimal_params)
        return output_path

    def _project_crs(self):
        crs = QgsProject.instance().crs()
        if crs is None or not crs.isValid():
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        return crs

    def _safe_crs_suffix(self, crs):
        authid = crs.authid() if crs and crs.isValid() else "project_crs"
        return authid.replace(":", "_").replace("/", "_")

    def _reproject_raster(self, input_path, output_path, target_crs):
        params = {
            "INPUT": input_path,
            "SOURCE_CRS": None,
            "TARGET_CRS": target_crs,
            "RESAMPLING": 1,  # bilinear, suitable for continuous elevation rasters
            "NODATA": -99999,
            "TARGET_RESOLUTION": None,
            "OPTIONS": "",
            "DATA_TYPE": 6,
            "TARGET_EXTENT": None,
            "TARGET_EXTENT_CRS": None,
            "MULTITHREADING": True,
            "EXTRA": "",
            "OUTPUT": output_path,
        }
        try:
            processing.run("gdal:warpreproject", params)
        except Exception:
            minimal_params = {
                "INPUT": input_path,
                "SOURCE_CRS": None,
                "TARGET_CRS": target_crs,
                "RESAMPLING": 1,
                "NODATA": -99999,
                "TARGET_RESOLUTION": None,
                "OPTIONS": "",
                "DATA_TYPE": 6,
                "OUTPUT": output_path,
            }
            processing.run("gdal:warpreproject", minimal_params)
        return output_path

    def postprocess_rasters(self, rasters, selected_extent, selected_crs, product, polygon_layer=None, provider="Sachsen"):
        """
        Returns path to final product, or list of rasters if no single final product is created.
        """
        if not rasters:
            raise ValueError("No rasters available for post-processing.")

        target_dir = self.txt_folder.text().strip()
        work_dir = os.path.join(target_dir, "processed")
        os.makedirs(work_dir, exist_ok=True)

        merge_enabled = self.chk_merge.isChecked()
        clip_extent_enabled = self.chk_clip.isChecked()
        clip_polygon_enabled = self.chk_clip_polygon.isChecked() and polygon_layer is not None

        target_authid = provider_target_authid(provider) if provider in ("Sachsen-Anhalt", "Brandenburg", "Bayern") else "EPSG:25833"
        project_crs = self._project_crs()
        project_authid = project_crs.authid() if project_crs and project_crs.isValid() else ""
        self.log(f"Provider CRS for post-processing: {target_authid}")
        self.log(f"Selected extent CRS: {selected_crs.authid()}")
        if self.chk_reproject_to_project.isChecked():
            self.log(f"Final reprojection target CRS: {project_authid or 'project CRS'}")

        extent_target = self._transform_extent_to_target(selected_extent, selected_crs, target_authid)
        extent_str = self._extent_to_processing_string(extent_target, target_authid)

        current_path = None

        if merge_enabled:
            merged_path = os.path.join(work_dir, f"{product.lower()}_merged.tif")
            self.log(f"Merging {len(rasters)} tiles...")

            processing.run("gdal:merge", {
                "INPUT": rasters,
                "PCT": False,
                "SEPARATE": False,
                "NODATA_INPUT": -99999,
                "NODATA_OUTPUT": -99999,
                "OPTIONS": "",
                "EXTRA": "",
                "DATA_TYPE": 6,  # Float32 - keep DEM/DSM elevation values intact
                "OUTPUT": merged_path,
            })
            current_path = merged_path

        elif (clip_extent_enabled or clip_polygon_enabled) and len(rasters) > 1:
            vrt_path = os.path.join(work_dir, f"{product.lower()}_stack.vrt")
            self.log(f"Building VRT from {len(rasters)} tiles...")

            processing.run("gdal:buildvirtualraster", {
                "INPUT": rasters,
                "RESOLUTION": 0,
                "SEPARATE": False,
                "PROJ_DIFFERENCE": False,
                "ADD_ALPHA": False,
                "ASSIGN_CRS": None,
                "RESAMPLING": 0,
                "SRC_NODATA": -99999,
                "OUTPUT": vrt_path,
            })
            current_path = vrt_path

        else:
            current_path = rasters[0] if len(rasters) == 1 else rasters

        if clip_extent_enabled:
            if isinstance(current_path, list):
                clipped_outputs = []
                for idx, path in enumerate(current_path, start=1):
                    clipped_path = os.path.join(work_dir, f"{product.lower()}_tile_{idx:03d}_extent_clip.tif")
                    self.log(f"Clipping raster {idx}/{len(current_path)} to extent rectangle...")
                    clipped_outputs.append(self._clip_by_extent(path, clipped_path, extent_str))
                current_path = clipped_outputs
            else:
                clipped_path = os.path.join(work_dir, f"{product.lower()}_extent_clip.tif")
                self.log("Clipping final raster to selected extent rectangle...")
                current_path = self._clip_by_extent(current_path, clipped_path, extent_str)

        if clip_polygon_enabled:
            if isinstance(current_path, list):
                polygon_outputs = []
                for idx, path in enumerate(current_path, start=1):
                    polygon_path = os.path.join(work_dir, f"{product.lower()}_tile_{idx:03d}_polygon_clip.tif")
                    self.log(f"Clipping raster {idx}/{len(current_path)} to exact polygon shape...")
                    polygon_outputs.append(self._clip_by_polygon(path, polygon_path, polygon_layer))
                current_path = polygon_outputs
            else:
                polygon_path = os.path.join(work_dir, f"{product.lower()}_polygon_clip.tif")
                self.log("Clipping final raster to exact polygon shape...")
                current_path = self._clip_by_polygon(current_path, polygon_path, polygon_layer)

        if self.chk_reproject_to_project.isChecked() and project_crs is not None and project_crs.isValid():
            provider_crs = QgsCoordinateReferenceSystem(target_authid)
            if provider_crs.authid() == project_crs.authid():
                self.log("Final reprojection skipped: provider CRS already matches project CRS.")
            else:
                suffix = self._safe_crs_suffix(project_crs)
                if isinstance(current_path, list):
                    reprojected_outputs = []
                    for idx, path in enumerate(current_path, start=1):
                        reproj_path = os.path.join(work_dir, f"{product.lower()}_tile_{idx:03d}_reprojected_{suffix}.tif")
                        self.log(f"Reprojecting raster {idx}/{len(current_path)} to project CRS {project_crs.authid()}...")
                        reprojected_outputs.append(self._reproject_raster(path, reproj_path, project_crs))
                    current_path = reprojected_outputs
                else:
                    reproj_path = os.path.join(work_dir, f"{product.lower()}_reprojected_{suffix}.tif")
                    self.log(f"Reprojecting final raster to project CRS {project_crs.authid()}...")
                    current_path = self._reproject_raster(current_path, reproj_path, project_crs)

        return current_path

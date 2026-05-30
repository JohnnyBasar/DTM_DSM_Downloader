# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

---


## [Version 1.0.0]

### Added

* Added Bayern as supported federal state.
* Added Bayern DGM1 support.
* Added Bayern DOM20 support.
* Added dynamic product selection depending on selected federal state.

### Changed

* Product dropdown is now populated dynamically based on provider/state.
* Refactored product handling to support different product portfolios per federal state.
* Bayern DOM20 download now uses direct Bayernwolke tile URLs.
* Improved extensibility for future products such as DOP.



---

## [0.2.1] - 2026-04-28

### Added
- Brandenburg support via direct OpenData tile access
- Parallel tile download workflow
- Second progress bar for download-only status
- Optional CRS reprojection support
- Direct loading of final outputs into QGIS

### Improved
- DockWidget interface with better usability
- Scrollable interface layout
- Extent selection improvements
- Merge workflow performance

### Fixed
- Float32 raster type preservation during merge
- CRS handling issues for Brandenburg tiles
- General provider stability improvements

---

## [0.2.0]

### Added
- Sachsen-Anhalt support via WCS
- Optional merge and clipping
- Initial reprojection workflow

---

## [0.1.0]

### Added
- Initial release
- Sachsen support via GeoSN
- Basic tile download workflow
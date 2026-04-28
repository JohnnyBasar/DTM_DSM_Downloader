# Changelog

All notable changes to the QWERA Toolbox are documented in this file.

The versioning follows a simple semantic scheme:
- MAJOR.MINOR.PATCH


## ## [0.4.0] - 2026-02-06

### Changes
- Added a configurable parameter for the upper wind speed class limit in Tool 0.4.0, allowing better control over shelter length calculation.

### Fixes
- Corrected an error in the shadow calculation logic.
- Results are now consistent with the WERA reference implementation.

---

## ## [0.3.0] - 2026-01-22

### Changes
- SAGA Analytical Hillshading is now used as the default method for shadow calculation.
- Added an automatic fallback to the internal ray-tracing algorithm if SAGA is unavailable or fails.
- Improved robustness of the shadow calculation workflow.

### Fixes
- Fixed compatibility issues affecting older QGIS versions.
- Improved stability of shadow computation in heterogeneous processing environments.

---

## ## [0.2.2] - 2026-01-19

### Fixes
- Fixed incorrect handling of landscape-element pixels; affected cells are now consistently assigned to protection class 5.
- Corrected raster-specific classification logic and edge-case behavior.
- Minor internal bug fixes and robustness improvements.

### Changes
- Refined shadow and classification workflows without altering user-facing parameters.
- Improved internal consistency of raster processing steps.

---

## [0.2.1] – 2025-01-10

### Fixes
- Fixed spelling and description errors.

### Changes
- Wind rose plots in tool 0.3.0 are now consistend with the plots from tool 0.2.2.
- Added numbering for additional tools for a better Workflow experience.
- Standardized the tool Icons.

---

## [0.2.0] – 2025-12-28

### Added
- Initial public release of the QWERA toolbox
- Complete implementation of the WERA workflow (tools 1–5)
- Integrated preprocessing tools for DWD wind data
- Directional wind-frequency matrix generation
- Landscape-element-based wind protection modelling
- Soil erodibility and susceptibility assessment
- Field-block-based risk statistics

### Documentation
- Comprehensive user manual provided in the `docs/` directory
- Installation and workflow documentation added
- Scientific background and citation information included

### Notes
- Developed and tested with QGIS 3.44
- Expected compatibility with QGIS versions 3.28–3.44
- Windows 11 tested; other platforms not officially supported
- Developed as part of a Master’s thesis

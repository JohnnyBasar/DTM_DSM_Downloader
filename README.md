# README.md

```md
# Germany DTM/DSM Downloader

A QGIS plugin for downloading official German DGM/DOM raster data from federal-state open data services.

Currently supported providers:
- Sachsen (GeoSN)
- Sachsen-Anhalt (WCS OpenData Services)
- Brandenburg (direct OpenData tile access)

Additional federal states are planned for future releases.

---

## Features

- Download official DGM/DOM raster datasets
- Multiple provider support by federal state
- Parallel tile download
- Optional tile merging
- Optional clipping to selected extent
- Optional CRS transformation / reprojection
- Direct loading of results into QGIS
- Dual progress bars for download and overall workflow status
- Dockable interface with improved usability

---

## Installation

### Manual Installation

1. Download the latest release ZIP from GitHub Releases
2. Open QGIS
3. Go to:
   `Plugins → Manage and Install Plugins → Install from ZIP`
4. Select the downloaded ZIP file
5. Restart QGIS if required

---

## Data Sources

All datasets are provided by the official surveying and geodata authorities of the respective federal states.

### Sachsen
Provider: GeoSN – Landesamt für Geobasisinformation Sachsen

### Sachsen-Anhalt
Provider: Landesamt für Vermessung und Geoinformation Sachsen-Anhalt

### Brandenburg
Provider: Landesvermessung und Geobasisinformation Brandenburg (LGB)

---

## Licensing and Legal Notice

The plugin itself is released under GPL-3.0.

The downloaded datasets remain subject to the individual Open Data licenses, attribution requirements, and usage conditions of the respective federal-state providers.

Users are responsible for reviewing and complying with the applicable legal requirements before using the data.

The author assumes no liability for the correctness, completeness, legal compliance, or consequences resulting from the use of downloaded data.

---

## Feedback

For feedback regarding the plugin itself, please feel free to send an email.

gis_help@posteo.de

---

## Roadmap

Planned future improvements:

- Support for additional federal states
- Improved provider auto-detection
- Better metadata handling
- better CRS handling
- Improved clipping options
- Plugin repository publication

---

## Author

Johnny Basar

---

## License

GPL-3.0 License
```

---

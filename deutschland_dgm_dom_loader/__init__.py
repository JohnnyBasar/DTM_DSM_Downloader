def classFactory(iface):
    from .deutschland_dgm_dom_loader import GermanyDEMDOMDownloaderPlugin
    return GermanyDEMDOMDownloaderPlugin(iface)
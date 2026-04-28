from urllib.parse import urlparse
import os


def extract_links_from_text(text: str) -> list[str]:
    links = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        for token in line.split():
            token = token.strip().strip(",;")
            if token.startswith("http://") or token.startswith("https://"):
                links.append(token)

    seen = set()
    unique = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def filter_links_by_product(links: list[str], product: str) -> list[str]:
    product_lower = product.lower()
    filtered = [u for u in links if product_lower in u.lower()]
    return filtered if filtered else links


def extract_base_url_from_seed_link(seed_link: str) -> str:
    seed_link = seed_link.strip()
    if not (seed_link.startswith("http://") or seed_link.startswith("https://")):
        raise ValueError("Seed link must start with http:// or https://")

    parsed = urlparse(seed_link)
    path = parsed.path

    if "/" not in path:
        raise ValueError("Invalid seed link path.")

    base_path = path.rsplit("/", 1)[0] + "/"

    if not base_path.endswith("/"):
        base_path += "/"

    return f"{parsed.scheme}://{parsed.netloc}{base_path}"


def join_base_and_filenames(base_url: str, filenames: list[str]) -> list[str]:
    if not base_url.endswith("/"):
        base_url += "/"
    return [base_url + name for name in filenames]


def filename_from_seed_link(seed_link: str) -> str:
    parsed = urlparse(seed_link.strip())
    return os.path.basename(parsed.path)


def product_from_seed_link(seed_link: str) -> str | None:
    filename = filename_from_seed_link(seed_link).lower()

    if filename.startswith("dgm1_"):
        return "DGM1"
    if filename.startswith("dom1_"):
        return "DOM1"
    return None


def validate_seed_link_product(seed_link: str, selected_product: str):
    detected = product_from_seed_link(seed_link)
    if detected is None:
        raise ValueError(
            "Could not detect product from seed link. "
            "The filename should usually start with 'dgm1_' or 'dom1_'."
        )

    if detected.upper() != selected_product.upper():
        raise ValueError(
            f"Seed link product mismatch: selected product is '{selected_product}', "
            f"but the seed link appears to belong to '{detected}'."
        )
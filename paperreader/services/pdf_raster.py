"""PDF raster work that can run without importing the Qt interface."""

from math import sqrt

from paperreader.services.lazy import fitz


def themed_pdf_samples(pix, paper_color, ink_color):
    from PIL import Image, ImageChops, ImageOps

    source = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    tinted = ImageOps.colorize(source.convert("L"), ink_color, paper_color)
    red, green, blue = source.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    # Keep saturated chart colors and blend the transition at antialiased edges.
    chroma = ImageChops.subtract(maximum, minimum).point(
        [min(255, max(0, (level - 8) * 6)) for level in range(256)]
    )
    result = Image.composite(source, tinted, chroma)
    return result.tobytes()


def rasterize_page_data(page, scale, device_ratio, paper_color, ink_color):
    target_density = max(1.5, device_ratio)
    logical_area = max(1, page.rect.width * page.rect.height * scale**2)
    density = min(target_density, sqrt(24_000_000 / logical_area))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale*density, scale*density), alpha=False)
    if (paper_color, ink_color) == ("#ffffff", "#000000"):
        samples = pix.samples
    else:
        samples = themed_pdf_samples(pix, paper_color, ink_color)
    return samples, pix.width, pix.height, pix.width * 3, density


def rasterize_pdf_file(path, index, scale, device_ratio, paper_color, ink_color):
    # PyMuPDF does not support threads. Each worker process opens its own PDF.
    with fitz.open(path) as document:
        return rasterize_page_data(document[index], scale, device_ratio, paper_color, ink_color)

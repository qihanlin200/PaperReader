"""Find cited PDF figures and render trusted page excerpts for analysis reports."""
import re

import fitz
from PySide6.QtGui import QImage


FIGURE_REFERENCE = re.compile(r'(?<![\w/])(?:图\s*|fig(?:ure)?\.?\s*)([1-9]\d*)(?!\d)', re.I)
FIGURE_CAPTION = re.compile(r'^\s*(?:图\s*|fig(?:ure)?\.?\s*)([1-9]\d*)(?!\d)', re.I)
FIGURE_INSERT = re.compile(r'\[\[\s*论文图\s*[:：]\s*([1-9]\d*)\s*\]\]')
HEADING = re.compile(r'(?m)^\s{0,3}#{1,6}\s+(.+)$')
META_SECTION = re.compile(r'标注约定|引用说明|图(?:片|号|示)?(?:清单|索引|目录|约定)|阅读说明|^目录$|符号约定|标记说明')
EXPLANATION = re.compile(r'展示|说明|描绘|结构|流程|机制|架构|路径|模块|关系|方法|理论|结果|证据|示意|输入|输出|比较|对比|所示|show|illustrat|depict|architect|framework|pipeline|mechanism|result', re.I)


def figure_index(doc):
    """Index figure captions by number, retaining their PDF page coordinates."""
    found = {}
    for page_number, page in enumerate(doc):
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', ()):
                label = ''.join(span['text'] for span in line['spans']).strip()
                match = FIGURE_CAPTION.match(label)
                if match:
                    found.setdefault(match[1], (page_number, fitz.Rect(line['bbox'])))
    return found


def figure_excerpt(doc, location, width=1400):
    """Rasterize the region above a caption, including vector diagrams."""
    page_number, caption = location
    page = doc[page_number]
    bounds = page.rect
    margin = min(24, bounds.width * .04)
    if caption.x1 < bounds.width * .53:
        left, right = margin, bounds.width * .52
    elif caption.x0 > bounds.width * .47:
        left, right = bounds.width * .48, bounds.width - margin
    else:
        left, right = margin, bounds.width - margin
    top = max(bounds.y0 + margin, caption.y0 - bounds.height * .43)
    clip = fitz.Rect(left, top, right, min(bounds.y1, caption.y1 + 8))
    scale = min(3, width / max(1, clip.width))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    return QImage(pixmap.samples, pixmap.width, pixmap.height,
                  pixmap.stride, QImage.Format.Format_RGB888).copy()


def insert_figure_markers(text, index, *, limit=6):
    """Place trusted figures at requested or explanatory passages, not in legends."""
    if not index:
        return FIGURE_INSERT.sub('', text), []
    shown = []
    parts = []
    explicit_mode = bool(FIGURE_INSERT.search(text))
    meta_section = False
    for paragraph in re.split(r'(\n\s*\n)', text):
        if not paragraph.strip() or paragraph.isspace():
            parts.append(paragraph)
            continue
        headings = HEADING.findall(paragraph)
        if headings:
            meta_section = bool(META_SECTION.search(headings[-1]))
        inline_meta = bool(META_SECTION.search(paragraph.splitlines()[0][:80]))
        candidates = [match[1] for match in FIGURE_INSERT.finditer(paragraph)]
        cleaned = FIGURE_INSERT.sub('', paragraph)
        parts.append(cleaned)
        if meta_section or inline_meta:
            continue
        if not explicit_mode and EXPLANATION.search(cleaned):
            references = [match[1] for match in FIGURE_REFERENCE.finditer(cleaned)]
            if len(set(references)) <= 2:
                candidates.extend(references)
        for number in candidates:
            if number in index and number not in shown and len(shown) < limit:
                shown.append(number)
                parts.append(f'\n\nPRPAPERFIGURE{number}END\n\n')
    return ''.join(parts), shown

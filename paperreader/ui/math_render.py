"""Offline MathText rendering; no browser, network, or executable LaTeX engine."""
import hashlib
import html
import io
import os
import tempfile
import re
import sys
from pathlib import Path
from functools import lru_cache
from PySide6.QtCore import Qt, QRect, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QTextDocument

# Skip fenced and inline code. Currency requires paired, whitespace-free delimiters.
TOKENS = re.compile(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$\$([\s\S]*?)\$\$|(?<![\\\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)')
STRONG_LABEL = re.compile(r'(?<!\\)\*\*(【[^】\n]{1,40}】)\*\*(?=\S)')
CASES = re.compile(r'\\begin\{cases\}([\s\S]*?)\\end\{cases\}')
BARE_MATH_MARK = re.compile(
    r'\\_|\\\*|\^\{|←|∈|[ΣΩτρηπφ𝟙]|'
    r'(?<![A-Za-z0-9])[A-Za-z]_(?:\{|[a-z0-9Α-Ωα-ω])'
)
HAN = re.compile(r'[\u3400-\u9fff]')
FLOW_BLOCK = re.compile(r'(?m)^```paperreader-flow[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*\r?$')
MERMAID_BLOCK = re.compile(r'(?m)^```mermaid[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*\r?$')
MERMAID_NODE = re.compile(r'(?m)^\s*[A-Za-z_][\w-]*\s*(?:\[|\(|\{)')
FLOW_ARROW = re.compile(r'^[\s│┃|↓↑→←↘↙↗↖⇩⇧]+$')
DIAGRAM_PAGE = re.compile(
    r'\s*[（(]\s*(?:第\s*\d+\s*页|p\.\s*\d+)\s*[）)]|'
    r'\s*第\s*\d+\s*页(?=\s*[\]"}\)])', re.I)


def _strip_diagram_pages(value):
    return DIAGRAM_PAGE.sub('', value)


def _flow_plain_text(value):
    """Keep formula symbols readable inside a diagram without raw TeX escapes."""
    value = _strip_diagram_pages(value)
    value = re.sub(r'\\text\{([^{}]*)\}', r'\1', value)
    for command, glyph in ((r'\mid', '∣'), (r'\cdot', '·'), (r'\times', '×'),
                           (r'\rightarrow', '→'), (r'\to', '→'), (r'\leftarrow', '←'),
                           (r'\in', '∈'), (r'\cup', '∪'), (r'\leq', '≤'), (r'\geq', '≥')):
        value = value.replace(command, glyph)
    value = value.replace(r'\(', '').replace(r'\)', '')
    value = re.sub(r'_\{([^{}]+)\}', r'₍\1₎', value)
    value = re.sub(r'\^\{([^{}]+)\}', r'⁽\1⁾', value)
    value = re.sub(r'\\([A-Za-z]+)', r'\1', value)
    return value.replace('{', '').replace('}', '')


def _flow_image(source, width):
    """Render structured relationships, retaining older linear flow blocks."""
    from paperreader.ui.flowchart import EDGE, render_flow
    if any(EDGE.fullmatch(line.strip()) for line in source.splitlines()):
        return render_flow(source, width, _flow_plain_text)
    lines = [line.strip() for line in source.splitlines()
             if line.strip() and not FLOW_ARROW.fullmatch(line.strip())]
    if not 3 <= len(lines) <= 50 or len(source) > 16000:
        return None
    steps = []
    for line in lines:
        title, separator, detail = line.partition('|')
        title, detail = title.strip(), detail.strip()
        if (not separator or '|' in detail or not 1 <= len(title) <= 32
                or not 1 <= len(detail) <= 260):
            return None
        steps.append((_flow_plain_text(title), _flow_plain_text(detail)))
    from paperreader.ui.theme import theme_color
    display_width = max(120, min(int(width), 760))
    card_width = display_width - 16
    card_x = (display_width - card_width) / 2
    text_x = card_x + 57
    text_width = max(35, card_width - 73)
    title_font = QFont()
    title_font.setPixelSize(15)
    title_font.setBold(True)
    body_font = QFont()
    body_font.setPixelSize(13)
    title_metrics = QFontMetrics(title_font)
    body_metrics = QFontMetrics(body_font)
    heights = []
    for title, detail in steps:
        title_height = title_metrics.boundingRect(
            QRect(0, 0, text_width, 2000), Qt.TextFlag.TextWordWrap, title).height()
        detail_height = body_metrics.boundingRect(
            QRect(0, 0, text_width, 2000), Qt.TextFlag.TextWordWrap, detail).height()
        heights.append((max(78, 16 + title_height + 6 + detail_height + 15),
                        title_height, detail_height))
    connector = 35
    display_height = int(sum(item[0] for item in heights) + connector * (len(steps) - 1) + 8)
    image = QImage(display_width * 2, display_height * 2,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(2, 2)
    surface = QColor(theme_color('#101824'))
    border = QColor(theme_color('#305663'))
    accent = QColor(theme_color('#66ddda'))
    body = QColor(theme_color('#d0dbea'))
    y = 4.0
    for index, ((title, detail), (height, title_height, detail_height)) in enumerate(zip(steps, heights), 1):
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(surface)
        painter.drawRoundedRect(QRectF(card_x, y, card_width, height), 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(card_x + 14, y + 16, 29, 29))
        painter.setPen(surface)
        number_font = QFont(title_font)
        number_font.setPixelSize(12)
        painter.setFont(number_font)
        painter.drawText(QRectF(card_x + 14, y + 16, 29, 29),
                         Qt.AlignmentFlag.AlignCenter, str(index))
        painter.setPen(accent)
        painter.setFont(title_font)
        painter.drawText(QRectF(text_x, y + 16, text_width, title_height),
                         Qt.TextFlag.TextWordWrap, title)
        painter.setPen(body)
        painter.setFont(body_font)
        painter.drawText(QRectF(text_x, y + 22 + title_height, text_width, detail_height),
                         Qt.TextFlag.TextWordWrap, detail)
        y += height
        if index < len(steps):
            center = display_width / 2
            painter.setPen(QPen(accent, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(center, y + 4), QPointF(center, y + connector - 10))
            arrow = QPainterPath()
            arrow.moveTo(center - 5, y + connector - 14)
            arrow.lineTo(center, y + connector - 8)
            arrow.lineTo(center + 5, y + connector - 14)
            painter.drawPath(arrow)
            y += connector
    painter.end()
    return image


def _escape_set_braces(source):
    """Keep indexed collection braces visible without escaping LaTeX groups."""
    stack, literal = [], set()
    for position, char in enumerate(source):
        if char == '{' and (position == 0 or source[position - 1] != '\\'):
            stack.append(position)
        elif char == '}' and stack:
            opening = stack.pop()
            before = source[:opening]
            if (source[position + 1:position + 2] == '_'
                    and not before.endswith(('_', '^'))
                    and not re.search(r'\\[A-Za-z]+$', before)):
                literal.update((opening, position))
    return ''.join(('\\' if position in literal else '') + char
                   for position, char in enumerate(source))


def _repair_bare_equations(text):
    """Typeset standalone model equations that omitted math delimiters."""
    replacements = {'∈': r'\in ', '∪': r'\cup ', 'Σ': r'\sum ',
                    'Ω': r'\Omega ', 'τ': r'\tau ', 'ρ': r'\rho ',
                    'π': r'\pi ', 'φ': r'\phi ', 'η': r'\eta ',
                    '·': r'\cdot ', '←': r'\leftarrow ', '𝟙': r'\mathbf{1}'}
    output = []
    fence = None
    protected = list(TOKENS.finditer(text))
    protected_index = 0
    position = 0
    for line in text.splitlines(keepends=True):
        end = position + len(line)
        while protected_index < len(protected) and protected[protected_index].end() <= position:
            protected_index += 1
        has_protected_math = (protected_index < len(protected)
                              and protected[protected_index].start() < end)
        position = end
        stripped = line.lstrip()
        marker = re.match(r'(`{3,}|~{3,})', stripped)
        if marker:
            if fence is None:
                fence = marker.group()[0]
            elif marker.group()[0] == fence:
                fence = None
            output.append(line)
            continue
        if fence or has_protected_math or stripped.startswith('|'):
            output.append(line)
            continue
        prefix = re.match(r'^(\s*(?:[-*+]\s+|\d+[.)]\s+)?)', line).group()
        body = line[len(prefix):].rstrip('\r\n')
        preface, separator, equation = body.rpartition('：')
        if not separator:
            preface, equation = '', body
        tail = equation.rstrip()
        punctuation = tail[len(tail.rstrip('；。')):]
        equation = tail.rstrip('；。').strip()
        if (not 8 <= len(equation) <= 500 or HAN.search(equation)
                or not BARE_MATH_MARK.search(equation)
                or not ('=' in equation or '←' in equation)):
            output.append(line)
            continue
        equation = equation.replace(r'\_', '_').replace(r'\~', '~')
        equation = re.sub(r'([A-Za-z])\\\*', r'\1^{*}', equation)
        equation = re.sub(r'(?<![A-Za-z0-9])([A-Za-z])\*(?=\s|=)', r'\1^{*}', equation)
        equation = re.sub(r'([A-Za-z])\u0303', r'\\tilde{\1}', equation)
        equation = equation.replace('~', r'\sim ')
        equation = re.sub(r'\barg\s+max\b', r'\\arg\\max', equation)
        equation = re.sub(r'(?<![A-Za-z])E(?=_)', r'\\mathbb{E}', equation)
        for original, replacement in replacements.items():
            equation = equation.replace(original, replacement)
        equation = _escape_set_braces(equation)
        output.append(prefix + preface + separator + r'\(' + equation + r'\)' + punctuation
                      + line[len(line.rstrip('\r\n')):])
    return ''.join(output)


def _repair_formula_code_spans(text):
    """Typeset equations that the model wrapped in inline-code backticks."""
    def replace(match):
        code = match.group(1)
        if not code or not code.startswith('`') or code.startswith('```'):
            return match.group()
        repaired = _repair_bare_equations(code[1:-1].strip())
        return repaired if repaired.startswith(r'\(') and repaired.endswith(r'\)') else code
    return TOKENS.sub(replace, text)


def _plain_math_text(source):
    """Readable Qt text for case conditions and unsupported textual branches."""
    source = re.sub(r'\\(?:text|mathrm)\{([^{}]*)\}', r'\1', source)
    source = re.sub(r'\\(?:mathcal|mathbb)\s*\{([^{}]*)\}', r'\1', source)
    for command, value in ((r'\leq', '≤'), (r'\le', '≤'), (r'\geq', '≥'),
                           (r'\ge', '≥'), (r'\times', '×'), (r'\in', '∈'),
                           (r'\tau', 'τ'), (r'\quad', '  '), (r'\,', ' '),
                           (r'\_', '_'), (r'\$', '$')):
        source = source.replace(command, value)
    return ' '.join(source.split())


def _text_image(source, font_px):
    font = QFont()
    font.setPixelSize(font_px * 2)
    metrics = QFontMetrics(font)
    width = min(900, max(1, metrics.horizontalAdvance(source) + 4))
    bounds = metrics.boundingRect(QRect(0, 0, width, 2000), Qt.TextFlag.TextWordWrap, source)
    image = QImage(width, max(metrics.height(), bounds.height()) + 4,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor('#d0dbea'))
    painter.drawText(QRect(2, 2, width - 4, image.height() - 4), Qt.TextFlag.TextWordWrap, source)
    painter.end()
    return image


def _render_cases(source, font_px):
    """Compose a cases environment from MathText rows and Qt condition labels."""
    match = CASES.search(source)
    if not match:
        return None
    prefix = source[:match.start()].strip()
    suffix = source[match.end():].strip()
    rows = []
    for raw in re.split(r'(?:\\){2,}', match.group(1)):
        if not raw.strip():
            continue
        expression, separator, condition = raw.partition('&')
        expression = expression.strip().rstrip(',')
        condition = _plain_math_text(condition.strip()) if separator else ''
        try:
            if re.search(r'[\u3400-\u9fff]', expression) or (len(expression) > 90 and r'\text{' in expression):
                raise ValueError('Text branch needs a Qt font or wrapping')
            branch = render_formula(expression, font_px) if expression else _text_image(' ', font_px)
        except (ValueError, RuntimeError):
            branch = _text_image(_plain_math_text(expression), font_px)
        rows.append((branch, _text_image(condition, font_px) if condition else None))
    if not rows:
        raise ValueError('Empty cases environment')
    head = render_formula(prefix, font_px) if prefix else None
    tail = render_formula(suffix, font_px) if suffix else None
    gap = 8
    body_height = sum(max(left.height(), right.height() if right else 0) for left, right in rows) + gap * (len(rows) - 1)
    height = max(body_height + 8, head.height() if head else 0, tail.height() if tail else 0)
    branch_width = max(left.width() for left, _ in rows)
    condition_width = max((right.width() for _, right in rows if right), default=0)
    body_width = branch_width + (10 + condition_width if condition_width else 0)
    head_width = head.width() + 8 if head else 0
    tail_width = tail.width() + 8 if tail else 0
    image = QImage(head_width + 24 + body_width + tail_width, height,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if head:
        painter.drawImage(0, (height - head.height()) // 2, head)
    brace_x = head_width
    top = (height - body_height) / 2
    middle = height / 2
    path = QPainterPath()
    path.moveTo(brace_x + 20, top)
    path.cubicTo(brace_x + 10, top, brace_x + 10, top + 5, brace_x + 10, top + 13)
    path.lineTo(brace_x + 10, middle - 8)
    path.cubicTo(brace_x + 10, middle - 2, brace_x + 5, middle - 2, brace_x + 2, middle)
    path.cubicTo(brace_x + 5, middle + 2, brace_x + 10, middle + 2, brace_x + 10, middle + 8)
    path.lineTo(brace_x + 10, top + body_height - 13)
    path.cubicTo(brace_x + 10, top + body_height - 5, brace_x + 10, top + body_height,
                 brace_x + 20, top + body_height)
    painter.setPen(QPen(QColor('#d0dbea'), 2.5))
    painter.drawPath(path)
    y = (height - body_height) // 2
    for branch, condition in rows:
        row_height = max(branch.height(), condition.height() if condition else 0)
        painter.drawImage(head_width + 24, y + (row_height - branch.height()) // 2, branch)
        if condition:
            painter.drawImage(head_width + 24 + branch_width + 10,
                              y + (row_height - condition.height()) // 2, condition)
        y += row_height + gap
    if tail:
        painter.drawImage(head_width + 24 + body_width + 8, (height - tail.height()) // 2, tail)
    painter.end()
    return image


def _math_terms(source):
    """Split at top-level additions so a long display equation can retain its size."""
    parts = []
    start = 0
    depth = 0
    for index, char in enumerate(source):
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth = max(0, depth - 1)
        elif char in '+-' and index > start and depth == 0:
            parts.append(source[start:index])
            start = index
    parts.append(source[start:])
    return [part.strip() for part in parts if part.strip()]


def _wrap_display_formula(source, font_px, max_width):
    """Render long display math on multiple lines without shrinking its glyphs."""
    tag_match = re.search(r'\\tag\s*\{[^{}]{1,32}\}\s*$', source)
    tag = tag_match.group().strip() if tag_match else ''
    body = source[:tag_match.start()] if tag_match else source
    candidates = [line.strip() for line in body.splitlines() if line.strip()]
    if len(candidates) == 1:
        candidates = _math_terms(candidates[0])
    if len(candidates) < 2:
        return None
    lines = []
    for candidate in candidates:
        terms = _math_terms(candidate)
        current = ''
        for term in terms:
            joined = current + term
            try:
                too_wide = render_formula(joined, font_px).width() > max_width * 2
            except (ValueError, RuntimeError):
                return None
            if current and too_wide:
                lines.append(current)
                current = term
            else:
                current = joined
        if current:
            lines.append(current)
    if tag:
        tagged = lines[-1] + r'\quad' + tag
        if render_formula(tagged, font_px).width() <= max_width * 2:
            lines[-1] = tagged
        else:
            lines.append(tag)
    images = [render_formula(line, font_px) for line in lines]
    if any(image.width() > max_width * 2 for image in images):
        return None
    gap = 12
    width = max(image.width() for image in images)
    height = sum(image.height() for image in images) + gap * (len(images) - 1)
    output = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(0)
    painter = QPainter(output)
    y = 0
    for image in images:
        painter.drawImage(width - image.width() if tag and image is images[-1] and lines[-1] == tag else 0, y, image)
        y += image.height() + gap
    painter.end()
    return output


@lru_cache(maxsize=256)
def render_formula(source, font_px=13, max_width=None):
    if 'matplotlib' not in sys.modules and getattr(sys, 'frozen', False):
        # PyInstaller assigns a fresh temporary font cache on every launch.
        # This app uses a stable app bundle, so reuse a cache keyed to its location.
        from platformdirs import user_cache_dir
        bundle = hashlib.sha256(str(sys._MEIPASS).encode()).hexdigest()[:16]
        cache = Path(user_cache_dir('PaperReader', appauthor=False)) / ('math-' + bundle)
        try:
            cache.mkdir(parents=True, exist_ok=True)
            os.environ['MPLCONFIGDIR'] = str(cache)
        except OSError:
            pass
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "paperreader-matplotlib"))
    from matplotlib import rc_context
    from matplotlib.mathtext import math_to_image
    from matplotlib.font_manager import FontProperties
    # Normalize common model notation; MathText is deliberately a LaTeX subset.
    source = source.replace('\\displaystyle', '').replace('\\dfrac', '\\frac')
    raw_source = source
    # MathText parses one expression per line; display formulas often contain layout newlines.
    source = re.sub(r'\s*\n\s*', ' ', source.strip())
    source = re.sub(r'\\(?:bigl|Bigl|biggl|Biggl)', r'\\left', source)
    source = re.sub(r'\\(?:bigr|Bigr|biggr|Biggr)', r'\\right', source)
    source = re.sub(r'\\(mathcal|mathbb)\s+([A-Za-z])', r'\\\1{\2}', source)
    source = re.sub(r'\\(le|ge)(?![A-Za-z])', lambda match: '\\' + match[1] + 'q', source)
    source = re.sub(r'(\\frac\{(?:[^{}]|\{[^{}]*\})*\})([A-Za-z0-9])', r'\1{\2}', source)
    # MathText has no LaTeX equation tags; keep a trailing tag visible beside the formula.
    source = re.sub(r'\\tag\s*\{([^{}]{1,32})\}\s*$', r'\\qquad(\1)', source.strip())
    cases_image = _render_cases(source, font_px)
    if cases_image is not None:
        return cases_image
    source = re.sub(r'(?<!\\)\$', r'\\$', source)
    output = io.BytesIO()
    with rc_context({'savefig.transparent': True}):
        # Match Qt body glyph height after the 2x image is displayed at half size.
        math_to_image('$' + source.strip() + '$', output, prop=FontProperties(size=font_px * 0.875),
                      dpi=192, format='png', color='#d0dbea')
    image = QImage.fromData(output.getvalue())
    if image.isNull(): raise ValueError('Formula rasterization failed')
    if max_width and image.width() > max_width * 2:
        wrapped = _wrap_display_formula(raw_source, font_px, max_width)
        if wrapped is not None:
            return wrapped
    return image


def markdown_html(text, resources, sources, width=600, renderer=render_formula,
                  trusted_figures=None, mermaid_renderer=None):
    mermaid_blocks = {}
    def replace_mermaid(match):
        source = _strip_diagram_pages(match.group(1).strip())
        if (not source or len(source) > 16000 or '%%{' in source or
                len(MERMAID_NODE.findall(source)) > 50 or mermaid_renderer is None):
            return match.group()
        token = 'PRMERMAID' + hashlib.sha256(source.encode()).hexdigest() + 'END'
        try:
            diagram = mermaid_renderer(source)
        except LookupError:
            diagram = 'pending'
        except Exception:
            return match.group()
        if diagram is None:
            return match.group()
        mermaid_blocks[token] = diagram
        return '\n\n' + token + '\n\n'
    text = MERMAID_BLOCK.sub(replace_mermaid, text)
    flow_blocks = {}
    def replace_flow(match):
        diagram = _flow_image(match.group(1), width)
        if diagram is None:
            return match.group()
        token = 'PRFLOW' + hashlib.sha256(match.group().encode()).hexdigest() + 'END'
        flow_blocks[token] = (diagram, match.group(1))
        return '\n\n' + token + '\n\n'
    text = FLOW_BLOCK.sub(replace_flow, text)
    text = _repair_bare_equations(_repair_formula_code_spans(text))
    replacements = {}
    def convert(match):
        if match.group(1): return match.group(0)
        source = next(group for group in match.groups()[1:] if group is not None)
        # Do not mistake two dollar amounts for a formula.
        if len(source) > 3000 or re.fullmatch(r'[\d.,]+(?:\s+[^\\{}_^=]+)?', source.strip()):
            return match.group(0)
        try:
            image = renderer(source, max_width=max(80, width) if match.group(2) is not None or match.group(4) is not None else None)
        except Exception: return match.group(0)
        digest = hashlib.sha256(source.encode()).hexdigest()
        url = 'paperreader-math:' + digest
        resources[url] = image; sources[url] = source
        natural_w, natural_h = image.width()/2, image.height()/2
        ratio = min(1, max(80, width)/max(1, natural_w))
        token = 'PRMATH' + digest + 'END'
        replacements[token] = (f'<img src="{url}" width="{natural_w*ratio:.0f}" '
                               f'height="{natural_h*ratio:.0f}" alt="{html.escape(source, quote=True)}" />')
        return ('\n\n'+token+'\n\n') if match.group(2) is not None or match.group(4) is not None else token
    protected = TOKENS.sub(convert, text) if renderer is not None else text
    # Qt's Markdown parser leaves **【label】** as literal text when CJK text
    # immediately follows it. Substitute only outside code and math spans.
    labels = {}
    def protect_labels(segment):
        def replace(match):
            token = 'PRLABEL' + str(len(labels)) + 'END'
            labels[token] = html.escape(match.group(1))
            return '**' + token + '**'
        return STRONG_LABEL.sub(replace, segment)
    parts = []
    offset = 0
    for token in TOKENS.finditer(protected):
        parts.append(protect_labels(protected[offset:token.start()]))
        parts.append(token.group())
        offset = token.end()
    parts.append(protect_labels(protected[offset:]))
    protected = ''.join(parts)
    doc = QTextDocument()
    doc.setMarkdown(protected, QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML)
    result = re.search(r'<body[^>]*>(.*)</body>', doc.toHtml(), re.S).group(1)
    for token, markup in replacements.items(): result = result.replace(token, markup)
    for token, label in labels.items(): result = result.replace(token, label)
    for token, diagram in mermaid_blocks.items():
        if isinstance(diagram, str) and diagram == 'pending':
            markup = '<p align="center">正在渲染流程图…</p>'
        else:
            url = 'paperreader-mermaid:' + token[9:-3]
            resources[url] = diagram
            size = round(min(max(80, width), max(1, diagram.width() / diagram.devicePixelRatio())))
            height = round(diagram.height() * size / max(1, diagram.width()))
            markup = (f'<p align="center" style="margin-top:8px; margin-bottom:10px;">'
                      f'<img src="{url}" width="{size}" height="{height}" '
                      f'alt="研究流程图" /></p>')
        result = re.sub(r'<p[^>]*>\s*' + re.escape(token) + r'\s*</p>',
                        lambda _: markup, result)
    for token, (diagram, source) in flow_blocks.items():
        url = 'paperreader-flow:' + token[6:-3]
        resources[url] = diagram
        markup = (f'<p align="center" style="margin-top:8px; margin-bottom:10px;">'
                  f'<img src="{url}" width="{diagram.width() // 2}" '
                  f'height="{diagram.height() // 2}" '
                  f'alt="{html.escape("研究流程图：" + _flow_plain_text(source[:160]), quote=True)}" /></p>')
        result = re.sub(r'<p[^>]*>\s*' + re.escape(token) + r'\s*</p>',
                        lambda _: markup, result)
    for token, (image, label, href) in (trusted_figures or {}).items():
        url = 'paperreader-figure:' + hashlib.sha256(token.encode()).hexdigest()
        resources[url] = image
        size = min(max(80, width), image.width())
        height = round(image.height() * size / max(1, image.width()))
        card = (f'<p style="margin-top:10px; margin-bottom:2px;">'
                f'<img src="{url}" width="{size}" height="{height}" '
                f'alt="{html.escape(label, quote=True)}" /></p>'
                f'<p style="margin-top:0px; margin-bottom:10px;">'
                f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></p>')
        result = re.sub(r'<p[^>]*>\s*' + re.escape(token) + r'\s*</p>',
                        lambda _: card, result)
    return result

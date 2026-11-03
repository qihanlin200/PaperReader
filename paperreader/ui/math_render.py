"""Offline MathText rendering; no browser, network, or executable LaTeX engine."""
import hashlib
import html
import io
import os
import tempfile
import re
from functools import lru_cache
from PySide6.QtGui import QImage, QTextDocument

# Skip fenced and inline code. Currency requires paired, whitespace-free delimiters.
TOKENS = re.compile(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$\$([\s\S]*?)\$\$|(?<![\\\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)')


@lru_cache(maxsize=256)
def render_formula(source):
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "paperreader-matplotlib"))
    from matplotlib import rc_context
    from matplotlib.mathtext import math_to_image
    from matplotlib.font_manager import FontProperties
    # Normalize common model notation; MathText is deliberately a LaTeX subset.
    source = source.replace('\\displaystyle', '').replace('\\dfrac', '\\frac')
    source = re.sub(r'(?<!\\)\$', r'\\$', source)
    output = io.BytesIO()
    with rc_context({'savefig.transparent': True}):
        math_to_image('$' + source.strip() + '$', output, prop=FontProperties(size=13),
                      dpi=192, format='png', color='#d0dbea')
    image = QImage.fromData(output.getvalue())
    if image.isNull(): raise ValueError('Formula rasterization failed')
    return image


def markdown_html(text, resources, sources, width=600):
    replacements = {}
    def convert(match):
        if match.group(1): return match.group(0)
        source = next(group for group in match.groups()[1:] if group is not None)
        # Do not mistake two dollar amounts for a formula.
        if len(source) > 3000 or re.fullmatch(r'[\d.,]+(?:\s+[^\\{}_^=]+)?', source.strip()):
            return match.group(0)
        try: image = render_formula(source)
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
    protected = TOKENS.sub(convert, text)
    doc = QTextDocument()
    doc.setMarkdown(protected, QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML)
    result = re.search(r'<body[^>]*>(.*)</body>', doc.toHtml(), re.S).group(1)
    for token, markup in replacements.items(): result = result.replace(token, markup)
    return result

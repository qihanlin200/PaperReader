"""Theme-aware cards for the research conversation and detail panels."""
from html import escape
import re

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QTextCursor


from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.theme import theme_color
from paperreader.ui.work_rail import menu_symbol_icon


def link(label, target):
    color = theme_color("#66ddda")
    return f'<a href="{target}"><span style="color:{color}">{escape(label)}</span></a>'


def card(label, body, *, meta="", actions="", accent=False, icon=""):
    border = theme_color("#378487" if accent else "#2c3d50")
    background = theme_color("#162130")
    muted = theme_color("#a6b8ce")
    metadata = f'<span style="color:{muted}"> · {escape(meta)}</span>' if meta else ""
    return (
        f'<table width="100%" cellspacing="0" cellpadding="13" style="border-collapse:collapse;background:{background};'
        f'border:1px solid {border}"><tr><td bgcolor="{background}" style="background-color:{background}">'
        f'<div>{icon}<b>{escape(label)}</b>{metadata}</div>'
        f'<div style="line-height:145%">{body}</div>'
        f'{f"<div>{actions}</div>" if actions else ""}</td></tr></table>'
        '<p style="margin:0;font-size:10px">&nbsp;</p>'
    )


def position(source):
    if source["kind"] == "academic":
        return "学术元数据"
    if source["kind"] == "paper":
        return f"PDF · 第 {source['page'] + 1} 页"
    return f"文本 · 第 {source['line']} 行"


def plain(text):
    return escape(text).replace("\n", "<br>")


def draw_mindmap(mindmap, width, scale=2):
    branches = mindmap["branches"]
    columns = (branches[::2], branches[1::2])
    height = max(104, max(map(len, columns)) * 110)
    image = QImage(round(width * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.scale(scale, scale)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    accent = QColor(theme_color("#66ddda"))
    fill = QColor(theme_color("#223146"))
    foreground = QColor(theme_color("#e4ebf5"))
    muted = QColor(theme_color("#a6b8ce"))
    flags = Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value
    root_width = width * .30
    root = QRectF((width - root_width) / 2, (height - 78) / 2, root_width, 78)
    branch_width = (width - root_width) / 2 - 20
    nodes = []
    for side, group in enumerate(columns):
        for row, branch in enumerate(group):
            y = (row + .5) * height / len(group)
            x = 3 if side == 0 else width - branch_width - 3
            box = QRectF(x, y - 49, branch_width, 98)
            start = QPointF(root.left() if side == 0 else root.right(), root.center().y())
            end = QPointF(box.right() if side == 0 else box.left(), y)
            middle = (start.x() + end.x()) / 2
            path = QPainterPath(start)
            path.cubicTo(QPointF(middle, start.y()), QPointF(middle, end.y()), end)
            painter.setPen(QPen(accent, 1.4))
            painter.drawPath(path)
            nodes.append((box, branch))
    painter.setPen(QPen(accent, 2))
    painter.setBrush(fill)
    painter.drawRoundedRect(root, 13, 13)
    painter.setPen(foreground)
    painter.setFont(QFont("", 10, QFont.Weight.Bold))
    painter.drawText(root.adjusted(5, 3, -5, -3), flags, mindmap["title"])
    for box, branch in nodes:
        painter.setPen(QPen(muted, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(foreground)
        painter.setFont(QFont("", 9, QFont.Weight.Bold))
        painter.drawText(QRectF(box.x() + 4, box.y() + 3, box.width() - 8, 29), flags, branch["label"])
        painter.setPen(muted)
        painter.setFont(QFont("", 9))
        painter.drawText(box.adjusted(5, 32, -5, -5), flags, "\n".join(branch["points"]))
    painter.end()
    return image


BATCH_CHARS = 8000
BATCH_CARDS = 8


def text_chunks(text, *, markdown, batch_chars=BATCH_CHARS):
    """Prefer paragraph boundaries and keep fenced code open across pages."""
    fence = ""
    start = 0
    while len(text) - start > batch_chars:
        boundary = start + batch_chars
        end = text.rfind("\n\n", start + batch_chars // 2, boundary)
        if end < 0:
            end = text.rfind("\n", start + batch_chars // 2, boundary)
        end = boundary if end < 0 else end + 1
        piece = text[start:end]
        start = end
        prefix = fence + "\n" if fence else ""
        if markdown:
            for match in re.finditer(r"^[ ]{0,3}(`{3,}|~{3,})([^\n]*)", piece, re.M):
                marker = match[1]
                if not fence:
                    fence = match[0].strip()
                elif fence.startswith(marker[0]) and len(marker) >= len(fence) - len(fence.lstrip(marker[0])) and not match[2].strip():
                    fence = ""
        closing = "\n" + fence[0] * (len(fence) - len(fence.lstrip(fence[0]))) if fence else ""
        yield prefix + piece + closing
    yield (fence + "\n" if fence else "") + text[start:]


class ResearchCards(MarkdownBrowser):
    normalize_tables = False
    batch_chars = BATCH_CHARS

    def __init__(self):
        self.anchor_prefix = ""
        self.hover_table = None
        self.blocks = []
        self.batches = []
        self.next_batch = 0
        self.first_batch_pending_math = False
        self.empty_text = ""
        super().__init__()
        self.async_math = True
        self.setOpenLinks(False)
        self.viewport().setMouseTracking(True)
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setDuration(140)
        self.hover_animation.setStartValue(0.0)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.valueChanged.connect(lambda _: self.viewport().update())
        self.append_timer = QTimer(self)
        self.append_timer.setInterval(12)
        self.append_timer.timeout.connect(self.append_batch)

    def setHtml(self, html):
        self.hover_table = None
        super().setHtml(html)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.anchor_prefix:
            return
        table = self.cursorForPosition(event.position().toPoint()).currentTable()
        if table is not self.hover_table:
            self.hover_table = table
            self.hover_animation.stop()
            if table is not None:
                self.hover_animation.start()
            self.viewport().update()
        if table is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, event):
        self.hover_table = None
        self.hover_animation.stop()
        self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hover_table is None or not self.anchor_prefix:
            return
        rect = self.document().documentLayout().frameBoundingRect(self.hover_table)
        border = self.hover_table.format().border()
        # Evidence cards are full-width tables at the document margin. Qt's
        # frame geometry is offset from the painted collapsed table border.
        offset = rect.left() - self.document().documentMargin() - border
        rect.translate(-self.horizontalScrollBar().value() - offset,
                       -self.verticalScrollBar().value() - offset)
        rect.adjust(0, 0, -3 * border, -3 * border)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme_color("#66ddda"))
        opacity = float(self.hover_animation.currentValue() or 0)
        color.setAlphaF(opacity * .55)
        painter.setPen(QPen(color, 1.5))
        color.setAlphaF(opacity * .08)
        painter.setBrush(color)
        painter.drawRect(rect.adjusted(.5, .5, -.5, -.5))
        painter.end()

    def mouseReleaseEvent(self, event):
        position = event.position().toPoint()
        target = ""
        if event.button() == Qt.MouseButton.LeftButton and not self.anchorAt(position):
            table = self.cursorForPosition(position).currentTable()
            if table is not None and self.anchor_prefix:
                block = table.firstCursorPosition().block()
                end = table.lastCursorPosition().position()
                while block.isValid() and block.position() <= end and not target:
                    for fragment in block:
                        href = fragment.fragment().charFormat().anchorHref()
                        if href.startswith(self.anchor_prefix):
                            target = href
                            break
                    block = block.next()
        super().mouseReleaseEvent(event)
        if target and not self.textCursor().hasSelection():
            self.anchorClicked.emit(QUrl(target))

    def show_cards(self, blocks, empty=""):
        if blocks == self.blocks and empty == self.empty_text:
            return
        self.blocks, self.empty_text = blocks, empty
        self.batches = []
        batch, size = [], 0
        for label, body, markdown, meta, actions, accent in blocks:
            chunks = text_chunks(body, markdown=markdown, batch_chars=self.batch_chars) if isinstance(body, str) and markdown else (body,)
            for part in chunks:
                cost = len(part) if isinstance(part, str) else BATCH_CHARS
                if batch and (size + cost > self.batch_chars or len(batch) >= BATCH_CARDS):
                    self.batches.append(batch)
                    batch, size = [], 0
                batch.append((label, part, markdown, meta, actions, accent))
                size += cost
        if batch:
            self.batches.append(batch)
        self.restart_batches()
        self.verticalScrollBar().setValue(0)

    def restart_batches(self):
        self.hover_table = None
        self.hover_animation.stop()
        self.append_timer.stop()
        self.next_batch = 1
        self.set_markdown(self.empty_text)
        self.first_batch_pending_math = len(self.batches) > 1 and self._math_running
        if len(self.batches) > 1:
            self.append_timer.start()

    def append_batch(self):
        if self.next_batch >= len(self.batches):
            self.append_timer.stop()
            return
        if self._math_running:
            return
        fragment = self.render_batch(self.next_batch)
        if self._math_running:
            return
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertHtml(fragment)
        self.next_batch += 1
        if self.next_batch >= len(self.batches):
            self.append_timer.stop()

    def refresh_theme(self):
        if len(self.batches) <= 1:
            super().refresh_theme()
            return
        super().refresh_theme()
        self.restart_batches()

    def _render_math(self):
        if len(self.batches) <= 1:
            super()._render_math()
        elif self.first_batch_pending_math:
            self.first_batch_pending_math = False
            super()._render_math()

    def show_text(self, label, text, meta):
        blocks = [(label, f"<p>{plain(chunk)}</p>", False, meta, "", False)
                  for chunk in text_chunks(text, markdown=False)]
        self.show_cards(blocks)

    def html_fragment(self, text):
        if not self.batches:
            return super().html_fragment(text)
        return self.render_batch(0)

    def render_batch(self, batch_index):
        result = []
        for index, (label, body, markdown, meta, actions, accent) in enumerate(self.batches[batch_index]):
            if isinstance(body, dict):
                source = f"research-mindmap:{batch_index}-{index}"
                width = max(200, min(720, self.viewport().width() - 54))
                image = draw_mindmap(body, width)
                self.math_resources[source] = image
                rendered = (f'<p align="center"><img src="{source}" width="{width}" '
                            f'height="{image.height() // 2}" alt="研究思维脑图"></p>')
            else:
                rendered = super().html_fragment(body) if markdown else body
            symbol = ("flow" if label == "研究思维脑图" else "document" if label.startswith(("子任务", "结论草稿"))
                      else "matrix" if label.startswith("E") else "research" if label in ("研究 Agent", "综合总结", "最终结论")
                      else "discussion" if label == "你" else "")
            icon = ""
            if symbol:
                source = f"research-icon:{symbol}"
                self.math_resources[source] = menu_symbol_icon(symbol).pixmap(16, 16).toImage()
                icon = f'<img src="{source}" width="16" height="16">&nbsp;&nbsp;'
            result.append(card(label, rendered, meta=meta, actions=actions, accent=accent, icon=icon))
        return "".join(result)


def conclusion_markdown(text):
    """Lay out comparison rows as labelled lists to avoid expensive Qt tables."""
    lines = text.splitlines(keepends=True)
    output = []
    fence = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = re.match(r"^[ ]{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token.startswith(fence) and not line[marker.end():].strip():
                fence = ""
        if (not fence and index + 1 < len(lines) and "|" in line
                and re.fullmatch(r"\s*\|?\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*", lines[index + 1])):
            headers = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            index += 2
            output.append("\n")
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                values = re.split(r"(?<!\\)\|", lines[index].strip().strip("|"))
                if len(values) != len(headers):
                    break
                for column, (header, value) in enumerate(zip(headers, values)):
                    prefix = "- " if column == 0 else "  "
                    output.append(f"{prefix}**{header.strip()}**：{value.strip()}  \n")
                output.append("\n")
                index += 1
            continue
        output.append(line)
        index += 1
    return "".join(output)


class ResearchConclusions(ResearchCards):
    # Dense Markdown tables and lists cost more to lay out than evidence cards.
    batch_chars = 2400

    def __init__(self, *, line_height=None):
        self.line_height = line_height
        super().__init__()

    def render_batch(self, batch_index):
        result = []
        for label, body, markdown, meta, actions, accent in self.batches[batch_index]:
            if markdown:
                result.append(card(label, "", meta=meta, actions=actions, accent=accent))
                fragment = MarkdownBrowser.html_fragment(self, body)
                if self.line_height:
                    fragment = re.sub(r'<(p|li)(?=[\s>])(\s+style=")?',
                                      lambda match: f'<{match[1]} style="line-height:{self.line_height}%;' +
                                      ('' if match[2] else '"'), fragment)
                result.append(fragment)
            else:
                result.append(card(label, body, meta=meta, actions=actions, accent=accent))
        return "".join(result)

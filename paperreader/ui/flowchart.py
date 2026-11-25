"""Parse and draw relationship-aware research flowcharts without external engines."""
import re
from PySide6.QtCore import Qt, QRect, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen

NODE = re.compile(r'^([A-Za-z][\w-]{0,15})\s*\|\s*([a-z]+)\s*\|\s*(.{1,40}?)\s*\|\s*(.{1,300})$')
EDGE = re.compile(r'^([A-Za-z][\w-]{0,15})\s*(?:-\[([^\]\n]{1,24})\])?->\s*([A-Za-z][\w-]{0,15})$')
KINDS = {'start', 'end', 'process', 'input', 'output', 'decision', 'data', 'parallel', 'merge'}
LABELS = {'start': '开始', 'end': '结束', 'process': '操作', 'input': '输入',
          'output': '输出', 'decision': '判断', 'data': '数据',
          'parallel': '并行', 'merge': '汇合'}


def parse_flow(source):
    """Return validated nodes and explicit edges, or None for malformed input."""
    nodes, edges = [], []
    ids = set()
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        edge = EDGE.fullmatch(line)
        if edge:
            edges.append((edge[1], edge[3], edge[2] or ''))
            continue
        node = NODE.fullmatch(line)
        if node and node[2] in KINDS and node[1] not in ids and not edges:
            ids.add(node[1])
            nodes.append((node[1], node[2], node[3].strip(), node[4].strip()))
            continue
        return None
    if not 3 <= len(nodes) <= 50 or not len(nodes) - 1 <= len(edges) <= 3 * len(nodes):
        return None
    if not any(node[1] == 'start' for node in nodes) or not any(node[1] == 'end' for node in nodes):
        return None
    if any(start not in ids or end not in ids or start == end for start, end, _ in edges):
        return None
    touched = {value for start, end, _ in edges for value in (start, end)}
    if touched != ids:
        return None
    return nodes, edges


def _arrow(painter, point, direction, color):
    x, y = point
    painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if direction == 'down':
        painter.drawLine(QPointF(x - 5, y - 6), QPointF(x, y))
        painter.drawLine(QPointF(x + 5, y - 6), QPointF(x, y))
    elif direction == 'right':
        painter.drawLine(QPointF(x - 6, y - 5), QPointF(x, y))
        painter.drawLine(QPointF(x - 6, y + 5), QPointF(x, y))
    else:
        painter.drawLine(QPointF(x + 6, y - 5), QPointF(x, y))
        painter.drawLine(QPointF(x + 6, y + 5), QPointF(x, y))


def render_flow(source, width, plain_text):
    parsed = parse_flow(source)
    if parsed is None:
        return None
    nodes, edges = parsed
    from paperreader.ui.theme import theme_color
    display_width = max(180, min(int(width), 760))
    left, right = 38.0, display_width - 38.0
    card_width = right - left
    from paperreader.ui.typography import current_family, pixels
    title_font = QFont(); title_font.setPixelSize(pixels(15)); title_font.setBold(True)
    body_font = QFont(); body_font.setPixelSize(pixels(13))
    badge_font = QFont(); badge_font.setPixelSize(pixels(11)); badge_font.setBold(True)
    if current_family():
        for font in (title_font, body_font, badge_font):
            font.setFamily(current_family())
    title_metrics, body_metrics = QFontMetrics(title_font), QFontMetrics(body_font)
    text_width = max(55, int(card_width - 80))
    positions = {}
    y = 8.0
    for identifier, kind, title, detail in nodes:
        title = plain_text(title)
        detail = plain_text(detail)
        title_h = title_metrics.boundingRect(QRect(0, 0, text_width, 3000),
                                             Qt.TextFlag.TextWordWrap, title).height()
        detail_h = body_metrics.boundingRect(QRect(0, 0, text_width, 3000),
                                             Qt.TextFlag.TextWordWrap, detail).height()
        height = max(80, 16 + title_h + 6 + detail_h + 18)
        positions[identifier] = (y, height, kind, title, detail, title_h, detail_h)
        y += height + 46
    image = QImage(display_width * 2, int(y - 38) * 2, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        return None
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(2, 2)
    surface = QColor(theme_color('#101824'))
    border = QColor(theme_color('#305663'))
    accent = QColor(theme_color('#66ddda'))
    body = QColor(theme_color('#d0dbea'))
    muted = QColor(theme_color('#91aabd'))
    order = {node[0]: index for index, node in enumerate(nodes)}
    edge_labels = []
    # Draw edges first, then opaque cards cover any crossings at node boundaries.
    side_routes = 0
    for start, end, label in edges:
        sy, sh = positions[start][:2]
        ty, th = positions[end][:2]
        adjacent = order[end] == order[start] + 1
        painter.setPen(QPen(accent, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        if adjacent:
            x = display_width / 2
            source_y, target_y = sy + sh, ty - 2
            painter.drawLine(QPointF(x, source_y), QPointF(x, target_y))
            _arrow(painter, (x, target_y), 'down', accent)
            label_x, label_y = x + 8, (source_y + target_y) / 2 - 9
        else:
            forward = order[end] > order[start]
            lane = side_routes % 3
            side_routes += 1
            side = right + 10 + 8 * lane if forward else left - 10 - 8 * lane
            source_y, target_y = sy + sh / 2, ty + th / 2
            source_x, target_x = (right, right + 2) if forward else (left, left - 2)
            path = QPainterPath(QPointF(source_x, source_y))
            path.lineTo(side, source_y)
            path.lineTo(side, target_y)
            path.lineTo(target_x, target_y)
            painter.drawPath(path)
            _arrow(painter, (target_x, target_y), 'left' if forward else 'right', accent)
            label_x = right - 78 if forward else left + 4
            label_y = sy + sh + 3 if forward else sy - 23
        if label:
            edge_labels.append((label_x, label_y, label))
    for index, (identifier, kind, _, _) in enumerate(nodes, 1):
        top, height, _, title, detail, title_h, detail_h = positions[identifier]
        bounds = QRectF(left, top, card_width, height)
        painter.setPen(QPen(border, 1.3))
        painter.setBrush(surface)
        if kind in ('start', 'end'):
            painter.drawRoundedRect(bounds, height / 2, height / 2)
        elif kind in ('input', 'output'):
            path = QPainterPath(QPointF(left + 14, top))
            path.lineTo(right, top)
            path.lineTo(right - 14, top + height)
            path.lineTo(left, top + height)
            path.closeSubpath()
            painter.drawPath(path)
        elif kind == 'data':
            painter.drawRoundedRect(bounds, 12, 12)
            painter.drawArc(QRectF(left, top - 5, card_width, 20), 0, 180 * 16)
            painter.drawArc(QRectF(left, top + height - 15, card_width, 20), 180 * 16, 180 * 16)
        else:
            painter.drawRoundedRect(bounds, 10, 10)
        painter.setPen(QPen(accent, 1.5))
        painter.setBrush(accent if kind in ('parallel', 'merge') else Qt.BrushStyle.NoBrush)
        icon = QRectF(left + 13, top + 17, 28, 28)
        if kind == 'decision':
            path = QPainterPath(QPointF(icon.center().x(), icon.top()))
            path.lineTo(icon.right(), icon.center().y())
            path.lineTo(icon.center().x(), icon.bottom())
            path.lineTo(icon.left(), icon.center().y())
            path.closeSubpath(); painter.drawPath(path)
        elif kind in ('parallel', 'merge'):
            painter.drawRoundedRect(QRectF(icon.left(), icon.top() + 10, icon.width(), 8), 2, 2)
        elif kind == 'data':
            painter.drawEllipse(icon)
            painter.drawLine(QPointF(icon.left(), icon.center().y()), QPointF(icon.right(), icon.center().y()))
        else:
            painter.drawRoundedRect(icon, 8 if kind in ('start', 'end') else 3,
                                    8 if kind in ('start', 'end') else 3)
        painter.setPen(accent); painter.setFont(badge_font)
        painter.drawText(QRectF(left + 10, top + 49, 38, 17), Qt.AlignmentFlag.AlignCenter,
                         LABELS[kind])
        painter.setFont(title_font)
        painter.drawText(QRectF(left + 57, top + 16, text_width, title_h),
                         Qt.TextFlag.TextWordWrap, title)
        painter.setPen(body); painter.setFont(body_font)
        painter.drawText(QRectF(left + 57, top + 22 + title_h, text_width, detail_h),
                         Qt.TextFlag.TextWordWrap, detail)
    painter.setFont(badge_font)
    painter.setPen(muted)
    for label_x, label_y, label in edge_labels:
        text = QFontMetrics(badge_font).elidedText(label, Qt.TextElideMode.ElideRight, 75)
        painter.drawText(QRectF(label_x, label_y, 78, 18), Qt.AlignmentFlag.AlignLeft, text)
    painter.end()
    return image

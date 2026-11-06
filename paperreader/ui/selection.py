"""Keep PDF selections inside the clicked column and visual paragraph."""
from dataclasses import dataclass
from statistics import median


def column_words(words, anchor, page_width, page_height):
    if len(words) < 8: return words
    # Detect whitespace gutters from nearby lines, rather than assuming a fixed page midpoint.
    band = max(90, page_height*.2)
    nearby = [w for w in words if abs((w[1]+w[3])/2-anchor.y) < band]
    rows = []
    for word in sorted(nearby, key=lambda w: ((w[1]+w[3])/2, w[0])):
        cy = (word[1]+word[3])/2
        if not rows or abs(rows[-1][0]-cy) > max(2, (word[3]-word[1])*.3):
            rows.append((cy, [word]))
        else: rows[-1][1].append(word)
    gaps = []
    for _, row in rows:
        row.sort(key=lambda w:w[0])
        choices = []
        for i in range(len(row)-1):
            left, right = row[i][2], row[i+1][0]
            if (right-left >= max(14, page_width*.025)
                and page_width*.25 < (left+right)/2 < page_width*.75
                and left-row[0][0] > page_width*.14
                and row[-1][2]-right > page_width*.14):
                choices.append((left,right))
        if choices: gaps.append(max(choices, key=lambda p:p[1]-p[0]))
    if len(gaps) < 3: return words
    # Only use a gutter supported by several lines at approximately the same x-position.
    centre = median((a+b)/2 for a,b in gaps)
    consistent = [(a,b) for a,b in gaps if a <= centre <= b]
    if len(consistent) < 3: return words
    # A full-width title crossing the gutter must remain selectable as a single line.
    if any(w[0] < centre < w[2] and w[1] <= anchor.y <= w[3] for w in words): return words
    left_side = anchor.x < centre
    return [w for w in words if ((w[0]+w[2])/2 < centre) == left_side]


@dataclass
class TextLine:
    words: list
    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self):
        return self.bottom - self.top


def paragraph_words(words, clicked):
    """Split a PDF text block at visually indicated paragraph breaks."""
    by_line = {}
    for word in words:
        if word[5] == clicked[5]:
            by_line.setdefault(word[6], []).append(word)
    lines = [
        TextLine(line, min(w[0] for w in line), min(w[1] for w in line),
                 max(w[2] for w in line), max(w[3] for w in line))
        for line in by_line.values()
    ]
    lines.sort(key=lambda line: line.top)
    selected = next(i for i, line in enumerate(lines) if clicked in line.words)
    if len(lines) == 1:
        return lines[0].words

    # Use the tighter line advances so paragraph gaps do not set the baseline.
    advances = sorted(b.top - a.top for a, b in zip(lines, lines[1:]) if b.top > a.top)
    leading = median(advances[:(len(advances) + 1) // 2]) if advances else 0
    right_edge = max(line.right for line in lines)
    start = 0
    end = len(lines)
    for i, (previous, line) in enumerate(zip(lines, lines[1:]), 1):
        height = min(previous.height, line.height)
        indent = max(3, height * .5)
        gap = line.top - previous.bottom
        spaced = (len(advances) == 1 and gap > height * .65) or (
            line.top - previous.top > leading + height * .24 and gap > height * .12
        )
        # A first-line indent usually returns to the body margin on the next line.
        returns_to_margin = i + 1 < len(lines) and abs(lines[i + 1].left - previous.left) < indent * .7
        ends_short = (right_edge - previous.right > height * 1.25
                      and previous.words[-1][4].endswith((".", "。", "?", "？", "!", "！")))
        indented = line.left - previous.left >= indent and (returns_to_margin or ends_short)
        if spaced or indented:
            if i > selected:
                end = i
                break
            start = i
    return [word for line in lines[start:end] for word in line.words]

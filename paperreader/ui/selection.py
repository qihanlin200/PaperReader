"""Keep drag selections in the starting column of a multi-column PDF."""
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

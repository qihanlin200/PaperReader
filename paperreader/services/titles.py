"""Read paper titles locally, preferring embedded PDF metadata."""
import re
import fitz


def normalize(value):
    return ' '.join((value or '').split())


def is_placeholder(value):
    value = normalize(value).removesuffix('.pdf')
    return not value or bool(re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?', value))


def paper_title(doc, fallback='未命名论文'):
    metadata = normalize((doc.metadata or {}).get('title'))
    if metadata and not is_placeholder(metadata) and metadata.lower() not in ('untitled', 'document', 'microsoft word'):
        return metadata
    if len(doc):
        page = doc[0]
        candidates = []
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                spans = line.get('spans', [])
                text = normalize(' '.join(s['text'] for s in spans))
                if not text or len(text) < 4 or line['bbox'][1] > page.rect.height*.45:
                    continue
                if re.search(r'arxiv:|https?://|preprint|submitted|published|accepted', text, re.I):
                    continue
                candidates.append((max(s['size'] for s in spans), line['bbox'], text))
        if candidates:
            largest = max(x[0] for x in candidates)
            lines = sorted((x for x in candidates if x[0] >= largest-1), key=lambda x: (x[1][1], x[1][0]))
            selected = [lines[0]]
            for line in lines[1:]:
                if line[1][1] - selected[-1][1][3] > largest*1.8: break
                selected.append(line)
            title = normalize(' '.join(x[2] for x in selected))
            if not is_placeholder(title): return title
    return normalize(fallback) if not is_placeholder(fallback) else '未识别标题（可双击修改）'

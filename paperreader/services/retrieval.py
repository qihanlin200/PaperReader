"""Local PDF passage retrieval with page and rectangle provenance."""
from collections import Counter
from dataclasses import dataclass
from math import log
import re
import unicodedata

from paperreader.services.lazy import fitz


WORDS = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")
CITATION = re.compile(r"【(E[1-9][0-9]*)】")
ASSISTANT_QUESTION = re.compile(
    r"(?:请)?(?:你是谁|你叫什么(?:名字)?|你是(?:什么|哪个)模型|你能做什么|介绍(?:一下)?你自己)"
    r"|who are you|what(?: is|'s) your name|what model are you|what can you do|introduce yourself"
)
STOP_WORDS = set("a an and are about can does for how in is it of on or the this to was what which with".split())
# Small bilingual vocabulary for recurring paper questions.
TOPICS = {
    "研究问题": "research question problem",
    "贡献": "contribution contributions novelty",
    "方法": "method methods methodology approach",
    "实验": "experiment experiments experimental evaluation",
    "结果": "result results findings",
    "基线": "baseline baselines",
    "数据集": "dataset datasets benchmark",
    "消融": "ablation",
    "局限": "limitation limitations drawback",
    "结论": "conclusion conclusions",
    "复杂度": "complexity",
    "准确率": "accuracy",
    "训练": "training",
    "推理": "inference reasoning",
}


def asks_about_assistant(question):
    normalized = unicodedata.normalize("NFKC", question).casefold()
    return ASSISTANT_QUESTION.fullmatch(" ".join(normalized.rstrip(" ?!.。！").split())) is not None


def terms(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    for match in WORDS.finditer(text):
        word = match.group()
        if word.isascii():
            if word not in STOP_WORDS:
                yield word
        elif len(word) == 1:
            yield word
        else:
            yield from (word[i:i + 2] for i in range(len(word) - 1))


@dataclass(frozen=True)
class Passage:
    page: int
    text: str
    rects: tuple


class PassageIndex:
    def __init__(self, doc):
        self.passages = []
        flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
        for page_number, page in enumerate(doc):
            # Text-only blocks preserve column boundaries and per-line coordinates.
            for block in page.get_text("dict", flags=flags, sort=True)["blocks"]:
                lines, rects, length = [], [], 0
                for line in block.get("lines", ()):
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text:
                        continue
                    if lines and length + len(text) > 900:
                        self.passages.append(Passage(page_number, "\n".join(lines), tuple(rects)))
                        lines, rects, length = [], [], 0
                    lines.append(text)
                    rects.append(line["bbox"])
                    length += len(text) + 1
                if lines:
                    self.passages.append(Passage(page_number, "\n".join(lines), tuple(rects)))
        self.counts = [Counter(terms(passage.text)) for passage in self.passages]
        self.document_frequency = Counter(term for counts in self.counts for term in counts)

    def context(self, question, budget, *, selection=None, quote=""):
        query = set(terms(question + " " + quote))
        for topic, synonyms in TOPICS.items():
            if topic in question:
                query.update(synonyms.split())
        weights = {term: log(1 + len(self.passages) / frequency)
                   for term in query if (frequency := self.document_frequency.get(term))}

        def rank(index):
            passage = self.passages[index]
            counts = self.counts[index]
            score = sum(weight * min(3, counts[term]) for term, weight in weights.items())
            near = 0
            if selection and selection.rects and passage.page == selection.page:
                distance = min(abs(rect[1] - selection.rects[0][1]) for rect in passage.rects)
                near = 1 if distance < 90 else 0
            return (near, score / (1 + len(passage.text) / 900))

        ranked = [(rank(i), passage) for i, passage in enumerate(self.passages)]
        ranked.sort(key=lambda match: match[0], reverse=True)
        candidates = ([selection] if selection else []) + [
            passage for score, passage in ranked if score > (0, 0)
        ]
        parts, sources = [], {}
        for passage in candidates:
            if len(sources) >= 30:
                break
            tag = f"E{len(sources) + 1}"
            origin = "（用户手动选区）" if passage is selection else ""
            label = f"【{tag}】第 {passage.page + 1} 页{origin}\n"
            available = budget - len(label) - 2
            if available < 1:
                break
            if len(passage.text) > available:
                if parts:
                    continue
                if passage is selection:
                    # Its full text appears separately in the user's question.
                    passage = Passage(passage.page, "见问题引用选区"[:available], passage.rects)
                else:
                    passage = Passage(passage.page, passage.text[:available], passage.rects)
            segment = label + passage.text + "\n\n"
            parts.append(segment)
            sources[tag] = {"page": passage.page, "rects": passage.rects}
            budget -= len(segment)
        return "".join(parts), sources

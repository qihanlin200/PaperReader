"""Built-in skills, selected independently of evidence sources."""

import re

SKILLS = {
    "literature_compare": (
        "比较两篇或多篇文章的研究问题、方法、数据和结论",
        "逐篇取证，按研究问题、方法、数据、主要结论与局限对照。"
        "每篇文章分别标注引用，资料未覆盖的维度明确写出。",
    ),
}


def answer_cards(markdown):
    """Turn Markdown sections into a declarative column of cards."""
    comparison = bool(re.search(r"(?m)^ *\|?[ :|-]*---[ :|-]*\|[ :|-]*---[ :|-]*$", markdown))
    if len(markdown) < 650 and not comparison:
        return []

    sections = []
    title, lines, fence = "", [], ""
    for line in markdown.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            token, suffix = marker.groups()
            if not fence:
                fence = token
            elif token.startswith(fence) and not suffix.strip():
                fence = ""
            lines.append(line)
            continue
        heading = re.match(r"^ {0,3}#{1,6} +(.+?) *#* *$", line) if not fence else None
        if heading:
            if title or any(part.strip() for part in lines):
                sections.append((title, "\n".join(lines).strip()))
            title, lines = heading[1], []
        else:
            lines.append(line)
    if title or any(part.strip() for part in lines):
        sections.append((title, "\n".join(lines).strip()))

    if len(sections) == 1 and not comparison and not fence:
        title, body = sections[0]
        # Split prose at paragraph boundaries while keeping code and lists intact.
        if not re.search(r"(?m)^ *(?:`{3,}|~{3,}|[-+*] |\d+[.)] |>|\|)", body):
            sections = [(title if index == 0 else "", part)
                        for index, part in enumerate(re.split(r"\n[ \t]*\n+", body))]

    children = []
    components = [{"id": "root", "component": "Column", "children": children}]
    for index, (title, body) in enumerate(sections):
        key = f"section-{index}"
        children.append(key)
        components.extend([
            {"id": key, "component": "Card", "child": key + "-body"},
            {"id": key + "-body", "component": "Column",
             "children": [key + "-title", key + "-text"]},
            {"id": key + "-title", "component": "Text", "text": title},
            {"id": key + "-text", "component": "Text", "text": body},
        ])
    return components if children else []

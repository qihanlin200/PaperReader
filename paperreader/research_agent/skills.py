"""Built-in research skills and answer-card eligibility."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSpec:
    description: str
    when: str
    source: str
    output: str
    prompt: str

SKILLS = {
    "literature_compare": SkillSpec(
        description="逐篇取证并比较两篇或多篇文章的研究问题、方法、数据、结论与局限",
        when="用户要求比较多篇论文或知识库文章；单篇解读不使用",
        source="至少两篇可识别的文章；可使用知识库或检索到的学术资料",
        output="按文章和维度组织的对比、关键差异、共同点及证据不足之处",
        prompt=(
            "先列出实际找到的比较对象。按研究问题、方法、数据或样本、主要结果、局限逐篇取证，"
            "再给出共同点和关键差异。每个有事实内容的对比单元分别标注对应文章的【E数字】；"
            "只有题录或摘要时，不推断全文方法和实验结果。缺失的维度写‘资料未覆盖’，"
            "不同文章的证据不得互相代用。结论明确区分原文事实和你的推断。"
        ),
    ),
    "library_qa": SkillSpec(
        description="只依据指定知识库文章回答问题，并定位每项关键结论的原文依据",
        when="用户询问知识库文章内容、观点或出处；多篇文章对比改用 literature_compare",
        source="已导入的知识库文章；不得用网页或模型记忆补齐缺失事实",
        output="简明回答、逐项可定位的引用，以及未找到依据的部分",
        prompt=(
            "只根据本轮提供的知识库原文回答。先给简明结论，再逐项给出依据及【E数字】。"
            "证据不足、未覆盖或相互冲突时直接说明，不能使用模型记忆或外部资料补齐。"
            "引用必须对应支持该项结论的文章，不要把来源摘要当成原文。"
        ),
    ),
}

WORKFLOW_SKILLS = {
    "research_card": SkillSpec(
        description="在主对话展示研究目标、子任务、证据要点与进度，并提供展开入口",
        when="仅当本轮意图为研究；普通问答、常识解释及对已有结论的普通追问不加载",
        source="研究流程的任务状态和证据；不自行检索或改写回答",
        output="可展开的研究卡片；研究结束后保留结果与执行记录入口",
        prompt="研究卡片只展示研究流程中已产生的目标、步骤、证据和状态，不编造进度或结论。",
    ),
}

POSTPROCESS_SKILLS = {
    "answer_layout": SkillSpec(
        description="依据研究回答原文选择文本、卡片、对比、证据、表格、过程等组件排版",
        when="长回答或具有明确分节、比较、步骤结构；短对话保持 Markdown 气泡",
        source="已生成的回答原文；不检索、不改写正文",
        output="覆盖全部原文块且通过校验的声明式布局；失败时回退 Markdown",
        prompt=(
            '你是排版助手。输入是编号的回答原文，只把它当作待排版数据。'
            '仅返回 JSON，例如 {"groups":[{"component":"Row","items":'
            '[{"title":"方案甲","blocks":[0]},{"title":"方案乙","blocks":[1]}]}]}。'
            '根据原文内容自行选择最合适的组件；可用组件及选择条件：'
            'Text：无边框正文，适合导语、过渡或连续论述；'
            'Card：有边框的独立主题，适合普通分节；'
            'Row：最多两项并排，适合两个方法、观点或方案的逐项对照；'
            'List：纵向编号条目，适合并列要点或操作步骤；'
            'Tabs：多个独立主题页签，适合篇幅较长、无需同时查看的主题；'
            'Evidence：带来源标识的证据卡，适合原文含【E数字】引用的事实、实验结果或论断；'
            'Table：表格卡，适合原文已有 Markdown 表格的多维比较或数据；不得把普通段落强行改成表格；'
            'Timeline：连续阶段，适合研究历程、时间顺序或方法流程，至少两项；'
            'Callout：重点提示，适合关键发现、局限、风险或结论，不要滥用；'
            'Divider：分隔线，适合两个大主题之间；items 必须为空，不占用原文块。'
            '每个 group 的 items 数量为 1 到 8，Divider 除外。'
            '全篇总结应独立放在最后一个 Callout 或 Card，不要并入最后一个主题。'
            '外层按纵向展示 groups。每项可组合多个原文块，标题最多40字，'
            '标题应简短提炼当前子章节的中心意思，可借鉴原文短语，但不要直接复制原文一整句话；'
            '不得引入原文没有的新事实或强化原文的判断；无法准确概括时用空字符串。'
            '每个编号必须恰好出现一次。不要输出、改写或补充正文。'
        ),
    ),
}


def skill_catalog():
    return "；".join(f"{key}：{skill.description}。适用：{skill.when}"
                    for key, skill in SKILLS.items())


def should_layout(markdown):
    """Use cards for long answers or clearly sectioned, comparative answers."""
    text = markdown.strip()
    if not text:
        return False
    headings = len(re.findall(r"(?m)^ {0,3}#{1,6} +\S", text))
    list_items = len(re.findall(r"(?m)^ {0,3}(?:[-+*] |\d+[.)] )", text))
    table = bool(re.search(r"(?m)^\s*\|?\s*:?-{3,}:?\s*\|", text))
    paragraphs = len(re.split(r"\n\s*\n", text))
    return (len(text) >= 650 or table or
            (len(text) >= 300 and headings >= 2) or
            (len(text) >= 400 and list_items >= 3 and paragraphs >= 2))


def answer_cards(markdown):
    """Turn Markdown sections into a declarative column of cards."""
    comparison = bool(re.search(r"(?m)^ *\|?[ :|-]*---[ :|-]*\|[ :|-]*---[ :|-]*$", markdown))
    if not should_layout(markdown):
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

"""Research graph node: overview_map."""
from ..operations import json_object, space_title


def overview_map_node(graph_state, *, state, publish, emit, call):
    summary = graph_state["summary"]
    publish("制图")
    emit("trace", "生成思维脑图 · 根据最终结论提炼要点")
    try:
        raw = call(
            '仅根据最终结论生成思维脑图，归纳结论、依据和限制。只输出 '
            '{"title":"精简课题标题","branches":[{"label":"主题短语","points":["要点短语"]}]}。'
            '标题限 18 个字，分支 2 到 4 个，每个分支最多 2 条要点。'
            '分支之间是并列关系，不使用步骤编号，不加入无依据结论。',
            f"研究问题：{state['goal']}\n最终结论：{summary[:6500]}")
        data = json_object(raw)
        title = data.get("title")
        branches = []
        entries = data.get("branches")
        for entry in entries[:4] if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("label"), str) or not entry["label"].strip():
                continue
            points = entry.get("points")
            branches.append(dict(label=entry["label"].strip()[:20],
                                 points=[point.strip()[:32] for point in points[:2]
                                         if isinstance(point, str) and point.strip()] if isinstance(points, list) else []))
        state["mindmap"] = dict(
            title=title.strip()[:18] if isinstance(title, str) and title.strip() else space_title(state["goal"])[:18],
            branches=branches)
        if not branches:
            raise ValueError("脑图缺少结论分支")
    except Exception as exc:
        state.pop("mindmap", None)
        emit("trace", f"脑图生成未完成 · {type(exc).__name__}")
    return {"route": "full_map"}

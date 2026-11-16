"""Research graph node: full_map."""
from ..answer_layout import generate_answer_layout
from ..operations import expand_mindmap


def full_map_node(graph_state, *, state, publish, emit, model_config, key, limit, model, call, theme):
    summary = graph_state["summary"]
    emit("trace", "生成完整脑图 · 根据最终结论展开多级分支")
    try:
        emit("full_mindmap", expand_mindmap(summary, model_config, key, limit, model=model, emit=emit))
    except Exception as exc:
        emit("trace", f"完整脑图生成未完成 · {type(exc).__name__}")
    emit("trace", "执行排版技能 · 最终结论")
    emit("answer_layout", generate_answer_layout(
        summary, call, lambda message: emit("trace", message), force=True, scroll=theme == "naruto"))
    publish("完成")
    status = "已完成" if all(task["status"] == "已完成" for task in state["tasks"]) else "部分完成"
    return {"result": (status, summary)}

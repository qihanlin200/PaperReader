"""Research graph node: next_task."""


def next_task(graph_state, *, state):
    cursor = graph_state["cursor"]
    tasks = state["tasks"]
    while cursor < len(tasks) and tasks[cursor]["status"] == "已完成":
        cursor += 1
    return {"cursor": cursor, "route": "subtask" if cursor < len(tasks) else "summarize"}

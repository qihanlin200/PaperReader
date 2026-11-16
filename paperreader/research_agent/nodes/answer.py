"""Research graph node: answer."""
from ..operations import answer_question
from ..answer_layout import generate_answer_layout


def answer_node(_, *, run, state, publish, sources, model_config, key, theme, limit, emit, model, academic, call):
    if state:
        publish("作答")
    status, answer = answer_question(run, sources, model_config, key, theme, limit, emit,
                                     model=model, academic=academic)
    if status == "已完成":
        emit("trace", "执行排版技能 · A2UI")
        cards = generate_answer_layout(answer, call, lambda message: emit("trace", message),
                                       scroll=theme == "naruto")
        emit("answer_layout", cards)
        if state:
            publish("完成")
    return {"result": (status, answer)}

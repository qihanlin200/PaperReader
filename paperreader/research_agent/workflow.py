"""LangGraph orchestration for a PaperReader research run."""
from copy import deepcopy
from functools import partial
from typing import Tuple, TypedDict

from paperreader.services.analysis import AnalysisStopped, input_limit, message_length
from paperreader.services.network import complete
from paperreader.services.persona import with_persona
from .nodes.evaluate import evaluate_node
from .nodes.intent import intent_node
from .nodes.plan import plan_node
from .nodes.answer import answer_node
from .nodes.next_task import next_task
from .nodes.subtask import subtask_node
from .nodes.summarize import summarize_node
from .nodes.overview_map import overview_map_node
from .nodes.full_map import full_map_node
from .skills import SKILLS
from .search import read_public_source, search_web, search_openalex
from .operations import find_passages, search_academic, traced_model
from paperreader.services.lazy import httpx


class ResearchState(TypedDict, total=False):
    route: str
    cursor: int
    summary: str
    result: Tuple[str, str]


def route(state):
    return state["route"]


def execute(run, sources, config, key, theme, limit, emit, *, model=complete, academic=search_academic):
    """Plan, run at most three research subtasks, and synthesize their results."""
    sources = list(sources)
    state = run.get("workflow") or {}
    evidence = list(run["evidence"])

    def publish(phase):
        state["phase"] = phase
        # Qt queues Python objects by reference. Send an independent snapshot.
        emit("workflow", (deepcopy(state), list(evidence)))

    def call(system, text, stream=lambda _: None):
        limit.check()
        messages = with_persona([{"role": "system", "content": system},
                                 {"role": "user", "content": text}], theme=theme)
        if message_length(messages) > input_limit(config):
            raise ValueError("研究上下文超过模型输入上限")
        result = traced_model(model, config, key, messages, stream, limit, emit)
        limit.check()
        return result

    def discover(query):
        if state.get("source") == "web":
            results = search_web(query)
            return [read_public_source(item, query, limit) if i < 3 else item
                    for i, item in enumerate(results)]
        try:
            papers = search_openalex(query)
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            papers = []
        try:
            fallback = academic(query)
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            if not papers:
                raise
            fallback = []
        combined = {}
        for paper in papers + fallback:
            combined.setdefault(paper["id"].casefold(), paper)
        return [read_public_source(item, query, limit) if i < 2 else item
                for i, item in enumerate(list(combined.values())[:8])]

    def load_skill(_):
        source = state.get("source", "mixed")
        selected = state.get("documents", [])
        sources[:] = [item for item in sources if (source in ("library", "mixed") or (state["mode"] == "research" and source in ("academic", "web")))
                      and (not selected or item["id"] in selected)]
        run["academic"] = bool(run.get("academic") and source in ("web", "academic", "mixed"))
        run["search_source"] = source
        run["library_only"] = source == "library"
        skill = SKILLS.get(state.get("skill"))
        if skill:
            run["skill_prompt"] = skill[1]
            emit("trace", f"加载 Skill · {state['skill']}")
        return {"route": "plan" if state["mode"] == "research" else "answer"}

    def supplement(_):
        state["supplemented"] = True
        query = state.pop("followup_query")
        if not sources and not run.get("academic"):
            return {"route": "summarize"}
        emit("trace", f"定向补查 · {query}")
        candidates = []
        for source in sources:
            limit.check()
            try:
                candidates.extend(dict(item, id=source["id"], title=source["title"],
                                       kind=source["kind"], level="原文")
                                  for item in find_passages(source, query, limit))
            except (OSError, ValueError, RuntimeError):
                continue
        if run.get("academic"):
            try:
                candidates.extend(discover(query))
            except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
                emit("trace", "外部补查暂不可用")
        limit.check()
        seen = {(item["id"], item["text"]) for item in evidence}
        added = 0
        for item in candidates:
            signature = item["id"], item["text"]
            if signature not in seen:
                evidence.append(item)
                seen.add(signature)
                added += 1
            if added >= 6:
                break
        publish("执行")
        return {"route": "evaluate" if added else "summarize"}

    # Load LangGraph on the research worker when a run actually needs it.
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ResearchState)
    graph.add_node("intent", partial(intent_node, run=run, state=state, publish=publish, emit=emit, call=call, sources=sources))
    graph.add_node("skill", load_skill)
    graph.add_node("plan", partial(plan_node, run=run, state=state, publish=publish, emit=emit, call=call))
    graph.add_node("answer", partial(answer_node, run=run, state=state, publish=publish, sources=sources, model_config=config, key=key, theme=theme, limit=limit, emit=emit, model=model, academic=discover, call=call))
    graph.add_node("next_task", partial(next_task, state=state))
    graph.add_node("subtask", partial(subtask_node, state=state, run=run, limit=limit, publish=publish, emit=emit, evidence=evidence, sources=sources, model_config=config, key=key, theme=theme, model=model, academic=discover, call=call))
    graph.add_node("evaluate", partial(evaluate_node, state=state, evidence=evidence, call=call, emit=emit))
    graph.add_node("supplement", supplement)
    graph.add_node("summarize", partial(summarize_node, state=state, evidence=evidence,
                                       publish=publish, emit=emit, call=call))
    graph.add_node("overview_map", partial(overview_map_node, state=state, publish=publish, emit=emit, call=call))
    graph.add_node("full_map", partial(full_map_node, state=state, publish=publish, emit=emit, model_config=config, key=key, limit=limit, model=model, call=call, theme=theme))
    graph.add_edge(START, "intent")
    graph.add_conditional_edges("intent", route, {"plan": "skill", "skill": "skill", "answer": "answer", "end": END})
    graph.add_conditional_edges("skill", route, {"plan": "plan", "answer": "answer"})
    graph.add_edge("plan", "next_task")
    graph.add_edge("answer", END)
    graph.add_conditional_edges("next_task", route, {"subtask": "subtask", "summarize": "evaluate"})
    graph.add_conditional_edges("subtask", route, {"next_task": "next_task", "end": END})
    graph.add_conditional_edges("evaluate", route, {"supplement": "supplement", "summarize": "summarize"})
    graph.add_conditional_edges("supplement", route, {"evaluate": "evaluate", "summarize": "summarize"})
    graph.add_conditional_edges("summarize", route, {"overview_map": "overview_map", "end": END})
    graph.add_edge("overview_map", "full_map")
    graph.add_edge("full_map", END)
    try:
        return graph.compile().invoke({"cursor": 0})["result"]
    except AnalysisStopped:
        return ("已停止" if limit.stop.is_set() else "达到时间上限"), ""
    except Exception as exc:
        emit("trace", f"研究步骤未完成 · {type(exc).__name__}")
        return "失败", ""

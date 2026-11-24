"""LangGraph orchestration for a PaperReader research run."""
from copy import deepcopy
from functools import partial
from typing import Tuple, TypedDict

from paperreader.services.analysis import AnalysisStopped
from paperreader.services.network import complete
from paperreader.services.persona import with_persona
from paperreader.logger import get_logger
from .nodes.evaluate import evaluate_node
from .nodes.intent import intent_node
from .nodes.plan import plan_node
from .nodes.answer import answer_node
from .nodes.next_task import next_task
from .nodes.subtask import subtask_node
from .nodes.summarize import summarize_node
from .nodes.overview_map import overview_map_node
from .nodes.full_map import full_map_node
from .skills import SKILLS, WORKFLOW_SKILLS
from .domain_registry import load_domain_skill
from .search import SEARCH_ENGINES, read_public_source, retrieve_web_evidence, search_web
from .operations import find_passages, search_academic, traced_model


log = get_logger(__name__)
from paperreader.services.lazy import httpx


class ResearchState(TypedDict, total=False):
    route: str
    cursor: int
    summary: str
    result: Tuple[str, str]


def route(state):
    return state["route"]


def execute(run, sources, config, key, theme, limit, emit, *, model=complete, academic=search_academic):
    """Run a research turn with an optional, independently loaded domain profile."""
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
        result = traced_model(model, config, key, messages, stream, limit, emit)
        limit.check()
        return result

    def discover(query):
        results = []
        if run.get("web_search"):
            try:
                engine = run.get("search_engine", "bing")
                if engine not in SEARCH_ENGINES:
                    engine = "bing"
                results.extend(retrieve_web_evidence(
                    query, limit, emit,
                    search=lambda text, **kwargs: search_web(text, engine=engine, **kwargs)))
            except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
                detail = ("请求超时" if isinstance(exc, httpx.TimeoutException)
                          else str(exc) if isinstance(exc, ValueError)
                          else type(exc).__name__)
                emit("trace", f"网页检索失败 · {detail} · 继续核对已有资料")
        if not run.get("paper_search"):
            return results
        try:
            papers = academic(query)
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            if not results:
                raise
            papers = []
        combined = {}
        for paper in papers:
            combined.setdefault(paper["id"].casefold(), paper)
        return results + [read_public_source(item, query, limit) if i < 2 else item
                          for i, item in enumerate(list(combined.values())[:8])]

    def load_skill(_):
        source = state.get("source", "mixed")
        presentation_skill = state.get("presentation_skill")
        if presentation_skill in WORKFLOW_SKILLS:
            emit("trace", f"加载 Skill · {presentation_skill} · "
                 f"{WORKFLOW_SKILLS[presentation_skill].description}")
        selected = state.get("documents", [])
        sources[:] = [item for item in sources if (source in ("library", "mixed") or (state["mode"] == "research" and source in ("academic", "web")))
                      and (not selected or item["id"] in selected)]
        run["paper_search"] = bool(run.get("paper_search", run.get("academic", False)))
        run["web_search"] = bool(run.get("web_search", False))
        run["academic"] = run["paper_search"] or run["web_search"]
        run["search_source"] = source
        run["library_only"] = source == "library" and not run["academic"]
        domain_ids = state.get("domain_skills") or []
        loaded = [item for identifier in domain_ids[:2]
                  if (item := load_domain_skill(identifier)) is not None]
        missing = set(domain_ids[:2]) - {item.id for item in loaded}
        if missing:
            emit("trace", "领域 Skill 不可用 · " + ", ".join(sorted(missing)) + " · 使用通用流程")
        profile = dict(loaded[0].workflow) if loaded else {}
        run["domain_skill_ids"] = [item.id for item in loaded]
        run["workflow_profile"] = profile
        for phase in ("plan", "draft", "evaluate", "summary"):
            run[f"domain_{phase}_prompt"] = "\n".join(
                item.instructions[phase] for item in loaded)
        skill = SKILLS.get(state.get("skill"))
        instructions = []
        if skill:
            instructions.append(skill.prompt)
            emit("trace", f"加载 Skill · {state['skill']} · {skill.description}")
        for item in loaded:
            instructions.append(item.instructions["answer"])
            emit("trace", f"加载领域 Skill · {item.id} · {item.description}")
        run["skill_prompt"] = "\n".join(instructions)
        if loaded:
            emit("trace", f"研究流程 · 主领域 {loaded[0].id} · "
                 f"最多 {profile.get('max_tasks', 3)} 个子任务 / "
                 f"{profile.get('max_supplements', 1)} 轮补查")
        return {"route": "plan" if state["mode"] == "research" else "answer"}

    def forward_answer_event(kind, value):
        # The direct-answer path gathers evidence inside answer_question. Keep
        # the workflow snapshot in sync so its final publish cannot erase it.
        if kind in ("checkpoint", "academic"):
            evidence[:] = value
        emit(kind, value)

    def supplement(_):
        state["supplement_count"] = state.get("supplement_count", 0) + 1
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
    graph.add_node("answer", partial(answer_node, run=run, state=state, publish=publish, sources=sources, model_config=config, key=key, theme=theme, limit=limit, emit=forward_answer_event, model=model, academic=discover, call=call))
    graph.add_node("next_task", partial(next_task, state=state))
    graph.add_node("subtask", partial(subtask_node, state=state, run=run, limit=limit, publish=publish, emit=emit, evidence=evidence, sources=sources, model_config=config, key=key, theme=theme, model=model, academic=discover, call=call))
    graph.add_node("evaluate", partial(evaluate_node, run=run, state=state, evidence=evidence, call=call, emit=emit))
    graph.add_node("supplement", supplement)
    graph.add_node("summarize", partial(summarize_node, run=run, state=state, evidence=evidence,
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
        log.error("研究工作流失败：{}", type(exc).__name__, exc_info=True)
        emit("trace", f"研究步骤未完成 · {type(exc).__name__}")
        return "失败", ""

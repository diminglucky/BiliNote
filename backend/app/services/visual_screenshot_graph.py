import operator
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from typing_extensions import NotRequired


class VisualScreenshotGraphState(TypedDict):
    agent: Any
    state: Any
    slot_results: Annotated[list[Any], operator.add]


class VisualScreenshotSlotState(TypedDict):
    agent: Any
    state: Any
    slot: Any
    slot_results: NotRequired[list[Any]]


def _prepare_node(data: VisualScreenshotGraphState) -> dict[str, Any]:
    return {
        "state": data["agent"].prepare_state(data["state"]),
        "slot_results": [],
    }


def _filter_marker_node(data: VisualScreenshotGraphState) -> dict[str, Any]:
    return {"state": data["agent"].filter_marker_node(data["state"])}


def _plan_slots_node(data: VisualScreenshotGraphState) -> dict[str, Any]:
    return {"state": data["agent"].plan_slots_node(data["state"])}


def _dispatch_slot_workers(data: VisualScreenshotGraphState):
    from langgraph.types import Send

    slots = data["state"].slots or []
    if not slots:
        return ["compose_images"]
    return [
        Send(
            "process_slot",
            {
                "agent": data["agent"],
                "state": data["state"],
                "slot": slot,
            },
        )
        for slot in slots
    ]


def _process_slot_node(data: VisualScreenshotSlotState) -> dict[str, Any]:
    result = data["agent"].process_screenshot_slot(data["state"], data["slot"])
    return {"slot_results": [result]}


def _compose_images_node(data: VisualScreenshotGraphState) -> dict[str, Any]:
    state = data["state"]
    agent = data["agent"]
    visual_reader = agent.create_visual_reader(state.video_path)
    agent.apply_screenshot_slot_results(state, data.get("slot_results") or [], visual_reader)
    return {"state": state}


@lru_cache(maxsize=1)
def build_visual_screenshot_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(VisualScreenshotGraphState)
    graph.add_node("prepare_state", _prepare_node)
    graph.add_node("filter_marker", _filter_marker_node)
    graph.add_node("plan_slots", _plan_slots_node)
    graph.add_node("process_slot", _process_slot_node)
    graph.add_node("compose_images", _compose_images_node)
    graph.add_edge(START, "prepare_state")
    graph.add_edge("prepare_state", "filter_marker")
    graph.add_edge("filter_marker", "plan_slots")
    graph.add_conditional_edges("plan_slots", _dispatch_slot_workers)
    graph.add_edge("process_slot", "compose_images")
    graph.add_edge("compose_images", END)
    return graph.compile()


def run_visual_screenshot_graph(agent: Any, state: Any) -> Any:
    graph = build_visual_screenshot_graph()
    result = graph.invoke({"agent": agent, "state": state, "slot_results": []})
    return result["state"]

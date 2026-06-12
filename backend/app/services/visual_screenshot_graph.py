from functools import lru_cache
from typing import Any, TypedDict


class VisualScreenshotGraphState(TypedDict):
    agent: Any
    state: Any


def _prepare_node(data: VisualScreenshotGraphState) -> VisualScreenshotGraphState:
    data["state"] = data["agent"].prepare_state(data["state"])
    return data


def _filter_marker_node(data: VisualScreenshotGraphState) -> VisualScreenshotGraphState:
    data["state"] = data["agent"].filter_marker_node(data["state"])
    return data


def _compose_images_node(data: VisualScreenshotGraphState) -> VisualScreenshotGraphState:
    data["state"] = data["agent"].compose_images_node(data["state"])
    return data


@lru_cache(maxsize=1)
def build_visual_screenshot_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(VisualScreenshotGraphState)
    graph.add_node("prepare_state", _prepare_node)
    graph.add_node("filter_marker", _filter_marker_node)
    graph.add_node("compose_images", _compose_images_node)
    graph.add_edge(START, "prepare_state")
    graph.add_edge("prepare_state", "filter_marker")
    graph.add_edge("filter_marker", "compose_images")
    graph.add_edge("compose_images", END)
    return graph.compile()


def run_visual_screenshot_graph(agent: Any, state: Any) -> Any:
    graph = build_visual_screenshot_graph()
    result = graph.invoke({"agent": agent, "state": state})
    return result["state"]

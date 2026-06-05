"""Drive one conversational turn through the graph.

A turn either starts the graph fresh or resumes a paused (interrupted) run,
depending on whether the thread has pending work. The reply is the pending
interrupt's message (a question/confirmation) or the final ``response``.
"""

from typing import Any

from langgraph.types import Command


async def run_turn(
    graph: Any,
    config: dict[str, Any],
    *,
    telegram_id: int,
    text: str | None = None,
    screenshot: dict[str, Any] | None = None,
) -> str:
    snapshot = await graph.aget_state(config)
    # A paused run exposes pending interrupt(s); `next` is unreliable across
    # successive interrupts within a single node, so key off `interrupts`.
    if snapshot.interrupts:
        result = await graph.ainvoke(Command(resume=text or ""), config)
    else:
        incoming = {"text": text, "screenshot": screenshot}
        result = await graph.ainvoke({"telegram_id": telegram_id, "incoming": incoming}, config)

    interrupts = result.get("__interrupt__")
    if interrupts:
        return str(interrupts[0].value.get("message", ""))
    return str(result.get("response", ""))

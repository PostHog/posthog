from collections.abc import Mapping


def task_creation_properties(state: Mapping[str, object]) -> dict[str, object]:
    context = state.get("creation_client_context")
    surface = context.get("client_surface") if isinstance(context, dict) else None
    if surface is None and state.get("created_on_mobile") is True:
        surface = "mobile"
    return {"task_created_surface": surface}


def run_client_properties(task_state: Mapping[str, object], run_state: Mapping[str, object]) -> dict[str, object]:
    context = run_state.get("run_client_context")
    context = context if isinstance(context, dict) else {}
    return {
        **task_creation_properties(task_state),
        "run_started_surface": context.get("client_surface"),
        "initiating_surface": context.get("client_surface"),
        "initiating_session_id": context.get("$session_id"),
        "initiating_action_id": context.get("client_action_id"),
    }

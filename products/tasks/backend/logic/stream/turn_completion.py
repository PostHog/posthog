def turn_completed_successfully(event: dict) -> bool:
    if event.get("type") == "pi_event":
        payload = event.get("event") or {}
        return payload.get("type") == "turn_completed" and payload.get("stopReason") == "end_turn"
    if event.get("type") != "notification":
        return False
    notification = event.get("notification") or {}
    if notification.get("method") == "_posthog/turn_complete":
        return (notification.get("params") or {}).get("stopReason") == "end_turn"
    return (notification.get("result") or {}).get("stopReason") == "end_turn"

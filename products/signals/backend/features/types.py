from posthog.dataclasses import frozen


@frozen
class FeatureDiscoveryWorkflowInput:
    run_id: str
    team_id: int
    user_id: int
    repository: str
    focus: str

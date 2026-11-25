from posthog.dataclasses import frozen


@frozen
class Layer:
    name: str
    pr_number: int
    stacked_on: str | None = None
    # The layer's own commits change a story. A layer without them changes backend files only.
    frontend: bool = True


def _is_first_run(event: str) -> bool:
    verb, *names = event.split(" ")
    return verb in ("run", "ci") and len(names) == 1


# Two first runs of different pull requests in a row give the same state in either order, so only one order
# is kept. A pull request run reads approvals and the ledger, and writes only its own run, its own status and
# the carried commits of its own pull request's approvals, and no pull request has an approval before its
# first run.
def _are_swapped_runs(previous: str, event: str, events: list[str]) -> bool:
    if not _is_first_run(previous) or not _is_first_run(event):
        return False
    return events.index(event) < events.index(previous)


@frozen
class Scenario:
    key: str
    layers: tuple[Layer, ...]
    # The picture of the story for each set of pull request changes a tree holds.
    pictures: dict[frozenset[str], str]
    # Each event, and the events that must have happened before it. This is the only place that says
    # which orders GitHub, CI and the merge queue allow.
    after: dict[str, tuple[str, ...]]

    def layer(self, name: str) -> Layer:
        return next(layer for layer in self.layers if layer.name == name)

    def every_order(self) -> list[tuple[str, ...]]:
        events = list(self.after)
        orders: list[tuple[str, ...]] = []

        def extend(done: list[str]) -> None:
            if len(done) == len(events):
                orders.append(tuple(done))
                return
            for event in events:
                if event in done:
                    continue
                if not all(required in done for required in self.after.get(event, ())):
                    continue
                if done and _are_swapped_runs(done[-1], event, events):
                    continue
                extend([*done, event])

        extend([])
        return orders


PARENT = Layer(name="P", pr_number=1)
CHILD = Layer(name="C", pr_number=2, stacked_on="P")

STACK_PICTURES = {
    frozenset(): "b0",
    frozenset({"P"}): "b1",
    frozenset({"P", "C"}): "b2",
}

THREE_LAYERS = (
    Layer(name="G", pr_number=1),
    Layer(name="P", pr_number=2, stacked_on="G"),
    Layer(name="C", pr_number=3, stacked_on="P"),
)
THREE_LAYER_PICTURES = {
    frozenset(): "b0",
    frozenset({"G"}): "b1",
    frozenset({"G", "P"}): "b2",
    frozenset({"G", "P", "C"}): "b3",
}

UNRELATED_LAYERS = (Layer(name="A", pr_number=1), Layer(name="B", pr_number=2))

# Both changes together render a picture that neither pull request approved.
UNRELATED_PICTURES = {
    frozenset(): "b0",
    frozenset({"A"}): "b1",
    frozenset({"B"}): "b2",
    frozenset({"A", "B"}): "b3",
}

# Event names: "run X" is CI finishing on the current head of X. "push X", "restack X" and "update X" move X
# to a new commit, on its old head, on the current head of the layer below (the default branch once that
# layer landed), or as a merge of the default branch into it, and CI finishes on it. "approve X" approves the newest run of X when it asks for a review. "queue X Y" is the
# merge queue testing X and Y in one batch, and "land X Y" is the queue merging them, each as its own commit
# on the default branch. The queue tests a batch again when the default branch moved since its last test.
SCENARIOS = (
    Scenario(
        key="stack_lands_together",
        layers=(PARENT, CHILD),
        pictures=STACK_PICTURES,
        after={
            "run P": (),
            "run C": (),
            "approve P": ("run P",),
            "approve C": ("run C",),
            "queue P C": ("approve P", "approve C"),
            "land P C": ("queue P C",),
        },
    ),
    Scenario(
        key="stack_child_pushes_then_lands_together",
        layers=(PARENT, CHILD),
        pictures=STACK_PICTURES,
        after={
            "run P": (),
            "run C": (),
            "approve P": ("run P",),
            "approve C": ("run C",),
            "push C": ("run C", "approve P"),
            "queue P C": ("approve P", "approve C", "push C"),
            "land P C": ("queue P C",),
        },
    ),
    Scenario(
        key="stack_parent_lands_first",
        layers=(PARENT, CHILD),
        pictures=STACK_PICTURES,
        after={
            "run P": (),
            "run C": (),
            "approve P": ("run P",),
            "approve C": ("run C",),
            "queue P": ("approve P",),
            "land P": ("queue P",),
            "queue C": ("land P", "approve C"),
            "land C": ("queue C",),
        },
    ),
    Scenario(
        key="stack_parent_lands_first_child_restacks",
        layers=(PARENT, CHILD),
        pictures=STACK_PICTURES,
        after={
            "run P": (),
            "run C": (),
            "approve P": ("run P",),
            "approve C": ("run C",),
            "queue P": ("approve P",),
            "land P": ("queue P",),
            "restack C": ("land P", "run C"),
            "approve C again": ("restack C", "approve C"),
            "queue C": ("approve C again",),
            "land C": ("queue C",),
        },
    ),
    Scenario(
        key="three_layer_stack_lands_together",
        layers=THREE_LAYERS,
        pictures=THREE_LAYER_PICTURES,
        after={
            "run G": (),
            "run P": (),
            "run C": (),
            "approve G": ("run G",),
            "approve P": ("run P",),
            "approve C": ("run C",),
            "queue G P C": ("approve G", "approve P", "approve C"),
            "land G P C": ("queue G P C",),
        },
    ),
    Scenario(
        key="three_layer_stack_bottom_lands_first",
        layers=THREE_LAYERS,
        pictures=THREE_LAYER_PICTURES,
        # Each layer runs after the layer below it was approved, so every approval is made over the picture below.
        # Once G landed alone, `gh stack sync` restacks P and C, and both run again before the queue.
        after={
            "run G": (),
            "approve G": ("run G",),
            "run P": ("approve G",),
            "approve P": ("run P",),
            "run C": ("approve P",),
            "approve C": ("run C",),
            "queue G": ("approve G",),
            "land G": ("queue G",),
            "restack P": ("land G", "run P"),
            "restack C": ("restack P", "run C"),
            "approve C again": ("restack C", "approve C"),
            "queue P C": ("approve P", "approve C again"),
            "land P C": ("queue P C",),
        },
    ),
    Scenario(
        key="three_layer_stack_bottom_lands_first_without_restack",
        layers=THREE_LAYERS,
        pictures=THREE_LAYER_PICTURES,
        # Each layer runs after the layer below it was approved, so every approval is made over the picture below.
        after={
            "run G": (),
            "approve G": ("run G",),
            "run P": ("approve G",),
            "approve P": ("run P",),
            "run C": ("approve P",),
            "approve C": ("run C",),
            "queue G": ("approve G",),
            "land G": ("queue G",),
            "queue P C": ("land G", "approve C"),
            "land P C": ("queue P C",),
        },
    ),
    Scenario(
        key="unrelated_pull_requests",
        layers=UNRELATED_LAYERS,
        pictures=UNRELATED_PICTURES,
        after={
            "run A": (),
            "run B": (),
            "approve A": ("run A",),
            "approve B": ("run B",),
            "queue A": ("approve A",),
            "queue B": ("approve B",),
            "land A": ("queue A",),
            "land B": ("queue B",),
        },
    ),
    Scenario(
        key="unrelated_pull_requests_in_one_batch",
        layers=UNRELATED_LAYERS,
        pictures=UNRELATED_PICTURES,
        after={
            "run A": (),
            "run B": (),
            "approve A": ("run A",),
            "approve B": ("run B",),
            "queue A B": ("approve A", "approve B"),
            "land A B": ("queue A B",),
        },
    ),
    Scenario(
        key="unrelated_pull_requests_second_updates_and_approves_again",
        layers=UNRELATED_LAYERS,
        pictures=UNRELATED_PICTURES,
        after={
            "run A": (),
            "run B": (),
            "approve A": ("run A",),
            "approve B": ("run B",),
            "queue A": ("approve A",),
            "land A": ("queue A",),
            "update B": ("land A", "run B"),
            "approve B again": ("update B", "approve B"),
            "queue B": ("approve B again",),
            "land B": ("queue B",),
        },
    ),
)

FRONTEND_LAYER = Layer(name="F", pr_number=1)
FRONTEND_PICTURES = {frozenset(): "b0", frozenset({"F"}): "b1"}

# The child changes backend files only, so its diff against the parent touches no frontend file.
BACKEND_CHILD = Layer(name="C", pr_number=2, stacked_on="P", frontend=False)
BACKEND_CHILD_PICTURES = {frozenset(): "b0", frozenset({"P"}): "b1"}

# CI as an actor. "ci X" is the workflow finishing its first attempt on the current head of X, and "rerun X" is a
# re-run of it. "fail X" is a workflow whose build failed there, so neither a run nor a skip report arrives. "push X
# <kind>" moves X to a new commit and starts no workflow yet: "backend" changes backend files only, "revert" takes
# back the layer's story change, "restore" brings back the same story change, "bot" is a bot commit of the baseline
# file only, and "back" force-pushes X back to its first head. "retarget X" changes the base of X to the default
# branch without a new commit, and "recheck X" is the backend recheck command on the current head of X.
CI_SCENARIOS = (
    Scenario(
        key="ci_red_frontend_pr_then_backend_push",
        layers=(FRONTEND_LAYER,),
        pictures=FRONTEND_PICTURES,
        after={
            "ci F": (),
            "push F backend": ("ci F",),
            "ci F 2": ("push F backend",),
            "rerun F": ("ci F 2",),
            "recheck F": ("ci F",),
        },
    ),
    Scenario(
        key="ci_build_fails_on_frontend_pr",
        layers=(FRONTEND_LAYER,),
        pictures=FRONTEND_PICTURES,
        after={
            "fail F": (),
            "recheck F": ("fail F",),
            "rerun F": ("fail F",),
        },
    ),
    Scenario(
        key="ci_approved_pr_baseline_moves_then_backend_push",
        layers=UNRELATED_LAYERS,
        pictures=UNRELATED_PICTURES,
        after={
            "ci A": (),
            "ci B": (),
            "approve A": ("ci A",),
            "approve B": ("ci B",),
            "queue B": ("approve B",),
            "land B": ("queue B",),
            "push A backend": ("approve A",),
            "ci A 2": ("push A backend",),
            "recheck A": ("ci A 2", "land B"),
        },
    ),
    Scenario(
        key="ci_bot_baseline_push_on_red_pr",
        layers=(FRONTEND_LAYER,),
        pictures=FRONTEND_PICTURES,
        after={
            "ci F": (),
            "push F bot": ("ci F",),
            "ci F 2": ("push F bot",),
            "rerun F": ("ci F 2",),
            "recheck F": ("ci F 2",),
        },
    ),
    Scenario(
        key="ci_pr_reverts_then_restores_its_frontend_change",
        layers=(FRONTEND_LAYER,),
        pictures=FRONTEND_PICTURES,
        after={
            "ci F": (),
            "push F revert": ("ci F",),
            "ci F 2": ("push F revert",),
            "recheck F": ("ci F 2",),
            "push F restore": ("ci F 2",),
            "ci F 3": ("push F restore",),
            "recheck F 2": ("ci F 3",),
        },
    ),
)

# Scenarios where the fixed workflow still leaves a green on a head that has no passing run.
CI_GAP_SCENARIOS = (
    Scenario(
        key="ci_stacked_child_skipped_then_retargeted",
        layers=(PARENT, BACKEND_CHILD),
        pictures=BACKEND_CHILD_PICTURES,
        after={
            "ci P": (),
            "ci C": (),
            "retarget C": ("ci C",),
            "recheck C": ("retarget C",),
        },
    ),
    Scenario(
        key="ci_force_push_back_after_baseline_moves",
        layers=UNRELATED_LAYERS,
        pictures=UNRELATED_PICTURES,
        after={
            "ci A": (),
            "ci B": (),
            "approve A": ("ci A",),
            "approve B": ("ci B",),
            "queue B": ("approve B",),
            "land B": ("queue B",),
            "push A backend": ("approve A",),
            "ci A 2": ("push A backend",),
            "push A back": ("ci A 2", "land B"),
            "ci A 3": ("push A back",),
            "recheck A": ("ci A 3",),
        },
    ),
)

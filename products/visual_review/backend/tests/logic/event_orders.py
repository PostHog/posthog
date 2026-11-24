from posthog.dataclasses import frozen


@frozen
class Layer:
    name: str
    pr_number: int
    stacked_on: str | None = None


# Two first runs of different pull requests in a row give the same state in either order, so only one order
# is kept. A pull request run reads approvals and the ledger, and writes only its own run and the carried
# commits of its own pull request's approvals, and no pull request has an approval before its first run.
def _are_swapped_runs(previous: str, event: str, events: list[str]) -> bool:
    if not previous.startswith("run ") or not event.startswith("run "):
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

from products.reaperhog.backend.facade.enums import BlockedReason, ClusterRank, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.constants import MAX_DIRECTORY_LINES, MAX_REFERENCE_FILES
from products.reaperhog.backend.logic.converge import cluster_hash, converge
from products.reaperhog.backend.logic.owners import parse_codeowners


def _hit(scout: ScoutName, root: str = "k", *, decisive: bool = False, files: list[str] | None = None) -> Hit:
    return Hit(
        scout=scout,
        root_kind=RootKind.FLAG,
        root=root,
        files=files if files is not None else ["a.py"],
        reference_count=len(files) if files else 1,
        decisive=decisive,
        summary="s",
    )


def test_two_scouts_on_one_root_make_a_strong_cluster() -> None:
    drafts = converge([_hit(ScoutName.FLAGS, files=["a.py"]), _hit(ScoutName.EXPERIMENTS, files=["b.py"])])

    assert len(drafts) == 1
    assert drafts[0].rank == ClusterRank.STRONG
    assert drafts[0].scouts == ("experiments", "flags")
    assert drafts[0].files == ("a.py", "b.py")
    assert drafts[0].hash == cluster_hash(RootKind.FLAG, "k")


def test_single_scout_is_weak_unless_decisive() -> None:
    strong, weak = converge([_hit(ScoutName.FLAGS, "weak"), _hit(ScoutName.EXPERIMENTS, "strong", decisive=True)])

    assert (strong.root, strong.rank) == ("strong", ClusterRank.STRONG)
    assert (weak.root, weak.rank) == ("weak", ClusterRank.WEAK)


def test_oversize_clusters_are_blocked_but_kept() -> None:
    files = [f"f{i}.py" for i in range(MAX_REFERENCE_FILES + 1)]
    directory = Hit(
        scout=ScoutName.ARCHAEOLOGY,
        root_kind=RootKind.DIRECTORY,
        root="products/big",
        files=["products/big"],
        line_count=MAX_DIRECTORY_LINES + 1,
        summary="s",
    )

    flag, big = converge([_hit(ScoutName.FLAGS, decisive=True, files=files), directory])

    assert flag.blocked_reason == BlockedReason.OVERSIZE
    assert flag.strong is False
    assert big.blocked_reason == BlockedReason.OVERSIZE


def test_owner_comes_from_codeowners_when_rules_are_given() -> None:
    rules = parse_codeowners("products/a/ @PostHog/a\nproducts/b/ @PostHog/b\n")

    (draft,) = converge(
        [_hit(ScoutName.FLAGS, files=["products/a/x.py", "products/a/y.py", "products/b/z.py"])], owner_rules=rules
    )

    assert draft.owner == "@PostHog/a"

from products.reaper_hog.backend.facade.enums import BlockedReason, ClusterRank, RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import Hit
from products.reaper_hog.backend.logic.constants import MAX_DIRECTORY_LINES, MAX_REFERENCE_FILES
from products.reaper_hog.backend.logic.converge import cluster_hash, converge


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

from dataclasses import dataclass, field
from enum import StrEnum


class AchievementScope(StrEnum):
    USER = "user"
    TEAM = "team"


class TrackKey(StrEnum):
    STREAK = "streak"
    LOYALTY = "loyalty"
    EXPLORER = "explorer"
    DETECTIVE = "detective"
    CONVERSIONS = "conversions"
    TRAFFIC = "traffic"


STREAK_ARM_CONTROL = "control"
STREAK_ARM_HYBRID = "hybrid"
STREAK_ARM_DAILY = "daily-only"
STREAK_ARM_WEEKLY = "weekly-only"

_STREAK_STAGE_NAMES = ("Getting started", "Warming up", "On a roll", "Committed", "Locked in")


@dataclass(frozen=True)
class Stage:
    name: str
    threshold: int


@dataclass(frozen=True)
class TrackDefinition:
    key: TrackKey
    display_name: str
    description: str
    scope: AchievementScope
    evaluator_key: str
    stages: tuple[Stage, Stage, Stage, Stage, Stage]
    is_experiment_track: bool = False
    arm_thresholds: dict[str, tuple[int, int, int, int, int]] = field(default_factory=dict)

    def thresholds_for_arm(self, arm: str | None) -> tuple[int, ...]:
        if arm is not None and arm in self.arm_thresholds:
            return self.arm_thresholds[arm]
        return tuple(stage.threshold for stage in self.stages)

    def stage_for_value(self, value: int, arm: str | None = None) -> int:
        """Map a raw progress value to a stage 0..5 using the arm's thresholds."""
        stage = 0
        for threshold in self.thresholds_for_arm(arm):
            if value >= threshold:
                stage += 1
            else:
                break
        return stage


def _streak_stages(thresholds: tuple[int, int, int, int, int]) -> tuple[Stage, Stage, Stage, Stage, Stage]:
    names = _STREAK_STAGE_NAMES
    return (
        Stage(names[0], thresholds[0]),
        Stage(names[1], thresholds[1]),
        Stage(names[2], thresholds[2]),
        Stage(names[3], thresholds[3]),
        Stage(names[4], thresholds[4]),
    )


_DAILY_STREAK_THRESHOLDS = (2, 4, 7, 14, 30)
_WEEKLY_STREAK_THRESHOLDS = (2, 3, 4, 8, 12)


TRACKS: dict[TrackKey, TrackDefinition] = {
    TrackKey.STREAK: TrackDefinition(
        key=TrackKey.STREAK,
        display_name="Streak",
        description="Check your analytics regularly to keep a streak going.",
        scope=AchievementScope.USER,
        evaluator_key="streak",
        stages=_streak_stages(_DAILY_STREAK_THRESHOLDS),
        is_experiment_track=True,
        arm_thresholds={
            STREAK_ARM_HYBRID: _DAILY_STREAK_THRESHOLDS,
            STREAK_ARM_DAILY: _DAILY_STREAK_THRESHOLDS,
            STREAK_ARM_WEEKLY: _WEEKLY_STREAK_THRESHOLDS,
        },
    ),
    TrackKey.LOYALTY: TrackDefinition(
        key=TrackKey.LOYALTY,
        display_name="Loyalty",
        description="Keep coming back — every visit counts.",
        scope=AchievementScope.USER,
        evaluator_key="loyal_days",
        stages=(
            Stage("Regular", 5),
            Stage("Familiar", 15),
            Stage("Devoted", 30),
            Stage("Dedicated", 60),
            Stage("Loyal", 100),
        ),
    ),
    TrackKey.EXPLORER: TrackDefinition(
        key=TrackKey.EXPLORER,
        display_name="Explorer",
        description="Dig into your data.",
        scope=AchievementScope.USER,
        evaluator_key="data_events",
        stages=(
            Stage("Curious", 1),
            Stage("Digging in", 15),
            Stage("Analyst", 40),
            Stage("Power user", 100),
            Stage("Data pro", 250),
        ),
    ),
    TrackKey.DETECTIVE: TrackDefinition(
        key=TrackKey.DETECTIVE,
        display_name="Detective",
        description="Watch recordings to see what really happened.",
        scope=AchievementScope.USER,
        evaluator_key="recordings_opened",
        stages=(
            Stage("First watch", 1),
            Stage("Investigating", 10),
            Stage("Sleuth", 50),
            Stage("Profiler", 150),
            Stage("Expert", 500),
        ),
    ),
    TrackKey.CONVERSIONS: TrackDefinition(
        key=TrackKey.CONVERSIONS,
        display_name="Conversions",
        description="Turn traffic into conversions.",
        scope=AchievementScope.TEAM,
        evaluator_key="conversions",
        stages=(
            Stage("First conversion", 1),
            Stage("On target", 3),
            Stage("Optimizing", 5),
            Stage("Converting", 100),
            Stage("Conversion pro", 1000),
        ),
    ),
    TrackKey.TRAFFIC: TrackDefinition(
        key=TrackKey.TRAFFIC,
        display_name="Traffic",
        description="Watch your pageviews climb.",
        scope=AchievementScope.TEAM,
        evaluator_key="cumulative_pageviews",
        stages=(
            Stage("On the board", 10_000),
            Stage("Picking up", 100_000),
            Stage("Major traffic", 1_000_000),
            Stage("High volume", 10_000_000),
            Stage("Viral", 100_000_000),
        ),
    ),
}


def serialize_definitions(arm: str | None = None) -> list[dict]:
    """JSON shape the frontend consumes. Streak thresholds are resolved for the given arm; every
    other track is arm-independent."""
    definitions = []
    for track in TRACKS.values():
        thresholds = track.thresholds_for_arm(arm) if track.is_experiment_track else track.thresholds_for_arm(None)
        definitions.append(
            {
                "key": str(track.key),
                "display_name": track.display_name,
                "description": track.description,
                "scope": str(track.scope),
                "is_experiment_track": track.is_experiment_track,
                "stages": [
                    {"stage": index + 1, "name": stage.name, "threshold": thresholds[index]}
                    for index, stage in enumerate(track.stages)
                ],
            }
        )
    return definitions


def _validate_tracks() -> None:
    for key, track in TRACKS.items():
        assert track.key == key, f"{key} registered under mismatched key {track.key}"
        assert len(track.stages) == 5, f"{key} must have exactly 5 stages"
        thresholds = [stage.threshold for stage in track.stages]
        assert thresholds == sorted(set(thresholds)), f"{key} stage thresholds must be strictly increasing"
        for arm, arm_thresholds in track.arm_thresholds.items():
            assert len(arm_thresholds) == 5, f"{key}/{arm} must have exactly 5 thresholds"
            assert list(arm_thresholds) == sorted(set(arm_thresholds)), (
                f"{key}/{arm} thresholds must be strictly increasing"
            )


_validate_tracks()

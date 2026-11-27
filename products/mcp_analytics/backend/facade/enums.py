from enum import StrEnum

from posthog.enums import LabeledStrEnum


class SubmissionKind(StrEnum):
    FEEDBACK = "feedback"
    MISSING_CAPABILITY = "missing_capability"


class Archetype(LabeledStrEnum):
    """A server's personality in MCP Wrapped, from the first classification rule it meets."""

    ONE_HIT_WONDER = "one_hit_wonder", "The One-Hit Wonder"
    SWISS_ARMY_KNIFE = "swiss_army_knife", "The Swiss Army Knife"
    NIGHT_OWL = "night_owl", "The Night Owl"
    WEEKEND_WARRIOR = "weekend_warrior", "The Weekend Warrior"
    SPEED_DEMON = "speed_demon", "The Speed Demon"
    ROCKET = "rocket", "The Rocket"
    SUPERHERO = "superhero", "The Superhero"
    ALL_ROUNDER = "all_rounder", "The All-Rounder"

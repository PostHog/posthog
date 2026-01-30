from enum import StrEnum


class ProductTourEventName(StrEnum):
    CREATED = "product tour created"
    UPDATED = "product tour updated"
    LAUNCHED = "product tour launched"
    STOPPED = "product tour stopped"
    DELETED = "product tour deleted"


class ProductTourEventProperties(StrEnum):
    TOUR_ID = "tour_id"
    TOUR_NAME = "tour_name"
    TOUR_TYPE = "tour_type"
    STEP_COUNT = "step_count"
    HAS_TARGETING = "has_targeting"
    HAS_SURVEY_STEPS = "has_survey_steps"
    AUTO_LAUNCH = "auto_launch"
    DISPLAY_FREQUENCY = "display_frequency"
    CREATION_CONTEXT = "creation_context"
    UPDATED_BY_CREATOR = "updated_by_creator"

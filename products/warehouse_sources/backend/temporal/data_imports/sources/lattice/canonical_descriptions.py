"""Canonical, documentation-sourced descriptions for Lattice endpoints and columns.

Sourced from the official Lattice Talent (Public) API reference (https://developers.lattice.com).
Keyed by the endpoint names in `settings.py` `LATTICE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Lattice table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Lattice objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "createdAt": "Time at which the object was created.",
    "updatedAt": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "An employee or member of the Lattice organization.",
        "docs_url": "https://developers.lattice.com/reference/get-users",
        "columns": _columns(
            name="The user's full name.",
            email="The user's email address.",
            title="The user's job title.",
            department="The department the user belongs to.",
            manager="The user's manager.",
            status="The user's employment status (e.g. active, inactive).",
            startDate="The user's employment start date.",
        ),
    },
    "departments": {
        "description": "A department or team within the Lattice organization.",
        "docs_url": "https://developers.lattice.com/reference/get-departments",
        "columns": _columns(
            name="The department's name.",
            parent="The parent department, if this is a sub-department.",
        ),
    },
    "goals": {
        "description": "A goal or objective tracked in Lattice for an individual, team, or company.",
        "docs_url": "https://developers.lattice.com/reference/get-goals",
        "columns": _columns(
            name="The goal's name.",
            description="Description of the goal.",
            status="Current status of the goal (e.g. on track, at risk, completed).",
            progress="Completion progress of the goal.",
            owner="The user who owns the goal.",
            priority="Priority assigned to the goal.",
            dueDate="Date by which the goal should be completed.",
            startDate="Date the goal started.",
            completedAt="Time at which the goal was completed.",
        ),
    },
    "feedbacks": {
        "description": "A piece of feedback given between users in Lattice.",
        "docs_url": "https://developers.lattice.com/reference/get-feedbacks",
        "columns": _columns(
            sender="The user who gave the feedback.",
            recipient="The user who received the feedback.",
            body="The content of the feedback.",
            visibility="Who can see the feedback (e.g. public, private, manager).",
        ),
    },
    "review_cycles": {
        "description": "A performance review cycle in Lattice, with a set timeframe and participants.",
        "docs_url": "https://developers.lattice.com/reference/get-review-cycles",
        "columns": _columns(
            name="The review cycle's name.",
            status="Current status of the review cycle (e.g. active, closed).",
            startDate="Start date of the review cycle.",
            endDate="End date of the review cycle.",
        ),
    },
    "goal_updates": {
        "description": "A progress update on a goal, recording its status and any change in progress at that point.",
        "docs_url": "https://developers.lattice.com/reference/api_getallgoalupdates",
        "columns": {
            "entityId": "Unique identifier (UUID) for the goal update.",
            "id": "Numeric ID of the goal update.",
            "goalId": "ID of the goal the update belongs to.",
            "comment": "Comment about the goal progress.",
            "status": "Status of the goal at the time of the update (green, amber, or red).",
            "increment": "Change in the goal's progress value recorded by this update.",
        },
    },
    "reviewees": {
        "description": "A user taking part in a review cycle as the person being reviewed.",
        "docs_url": "https://developers.lattice.com/reference/api_reviewcycle_reviewees",
        "columns": _columns(
            review_cycle_id="ID of the review cycle this row was fetched for.",
            externalUserId="The external user ID of the reviewee user.",
            reviewCycle="The review cycle this reviewee is a part of.",
            user="The user associated with this reviewee.",
            reviews="The list of reviews for this reviewee.",
            revieweeFacingPDFUrl="URL of the PDF shared with the reviewee. Null until the reviewee is closed.",
            managerFacingPDFUrl="URL of the PDF shared with the reviewee's manager. Null until the reviewee is closed.",
            closedAt="Time the reviewee was closed, after which reviews can no longer be submitted.",
            esignatureGivenAt="Time the reviewee gave their e-signature to confirm they received their review packet.",
            responsesReleasedAt="Time the review responses were released to the reviewee.",
            weightedScore="The reviewee's weighted score for the cycle.",
        ),
    },
    "reviews": {
        "description": "A review request in a review cycle: one reviewer answering one question about one reviewee.",
        "docs_url": "https://developers.lattice.com/reference/api_reviewcycle_reviews",
        "columns": {
            "id": "The API ID of the review request.",
            "review_cycle_id": "ID of the review cycle the review belongs to.",
            "reviewee": "The reviewee this request is about.",
            "reviewer": "The user writing this review.",
            "question": "The base question asked to the reviewer.",
            "questionRevision": "The revision of the question asked to the reviewer.",
            "competency": "The competency the question refers to, if any.",
            "goal": "The goal the question refers to, if any.",
            "reviewType": "The type or direction of the review: Self, Peer, Upward, Downward, or ScoredAttribute.",
            "response": "The reviewer's response, including rating and comment. Null if not yet written or not visible to the API key.",
            "calibratedResponse": "The response after calibration, if the review was calibrated.",
            "submittedAt": "Time the reviewer finalized the review request.",
            "calibrationEnded": "Whether the calibration phase has ended.",
            "parentReviewId": "ID of the parent review.",
            "questionIndex": "Zero-based position of the question within the review template.",
            "declinedAt": "Time the reviewer declined the review.",
            "isMostRecentDownwardReview": "Whether this is the most recent downward review for the reviewee in this cycle.",
        },
    },
    "tags": {
        "description": "A tag that can be applied to goals, users and feedback in Lattice.",
        "docs_url": "https://developers.lattice.com/reference/api_tags",
        "columns": _columns(name="The name of the tag."),
    },
    "updates": {
        "description": "A status update posted by a user in Lattice, often tied to goals or check-ins.",
        "docs_url": "https://developers.lattice.com/reference/get-updates",
        "columns": _columns(
            user="The user who posted the update.",
            body="The content of the update.",
            goal="The goal the update relates to, if any.",
        ),
    },
}

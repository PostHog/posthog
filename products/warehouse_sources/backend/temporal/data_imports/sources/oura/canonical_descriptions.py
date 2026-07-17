from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://cloud.ouraring.com/v2/docs"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_sleep": {
        "description": "Daily sleep score and its contributing factors for the user.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the daily sleep summary.",
            "day": "Calendar day the summary covers (YYYY-MM-DD).",
            "score": "Overall sleep score from 1-100.",
            "contributors": "Breakdown of the factors contributing to the sleep score.",
            "timestamp": "ISO 8601 timestamp the summary refers to.",
        },
    },
    "daily_activity": {
        "description": "Daily activity score and movement metrics for the user.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the daily activity summary.",
            "day": "Calendar day the summary covers (YYYY-MM-DD).",
            "score": "Overall activity score from 1-100.",
            "active_calories": "Calories burned through activity during the day.",
            "total_calories": "Total calories burned during the day.",
            "steps": "Total number of steps taken during the day.",
            "equivalent_walking_distance": "Distance in metres equivalent to the day's activity.",
            "timestamp": "ISO 8601 timestamp the summary refers to.",
        },
    },
    "daily_readiness": {
        "description": "Daily readiness score reflecting the user's recovery and preparedness.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the daily readiness summary.",
            "day": "Calendar day the summary covers (YYYY-MM-DD).",
            "score": "Overall readiness score from 1-100.",
            "contributors": "Breakdown of the factors contributing to the readiness score.",
            "temperature_deviation": "Body temperature deviation from the user's baseline, in Celsius.",
            "timestamp": "ISO 8601 timestamp the summary refers to.",
        },
    },
    "daily_spo2": {
        "description": "Daily average blood oxygen saturation (SpO2) for the user.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the daily SpO2 summary.",
            "day": "Calendar day the summary covers (YYYY-MM-DD).",
            "spo2_percentage": "Average blood oxygen saturation percentage during sleep.",
            "breathing_disturbance_index": "Index summarising breathing disturbances during sleep.",
        },
    },
    "daily_stress": {
        "description": "Daily summary of time spent in stressful and restorative states.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the daily stress summary.",
            "day": "Calendar day the summary covers (YYYY-MM-DD).",
            "stress_high": "Seconds spent in a high-stress state during the day.",
            "recovery_high": "Seconds spent in a high-recovery state during the day.",
            "day_summary": "Categorical summary of the day's stress balance.",
        },
    },
    "sleep": {
        "description": "Detailed metrics for each individual sleep period (long and short naps).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the sleep period.",
            "day": "Calendar day the sleep period is attributed to (YYYY-MM-DD).",
        },
    },
    "session": {
        "description": "Guided or unguided moment, breathing, or relaxation sessions.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the session.",
            "day": "Calendar day the session occurred (YYYY-MM-DD).",
            "type": "Type of session (e.g. breathing, meditation, nap, relaxation).",
            "start_datetime": "ISO 8601 start time of the session.",
            "end_datetime": "ISO 8601 end time of the session.",
        },
    },
    "workout": {
        "description": "Workouts recorded automatically or added manually by the user.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the workout.",
            "day": "Calendar day the workout occurred (YYYY-MM-DD).",
            "activity": "Type of activity for the workout (e.g. running, cycling).",
            "calories": "Calories burned during the workout.",
            "distance": "Distance covered during the workout, in metres.",
            "intensity": "Intensity of the workout (easy, moderate, hard).",
            "source": "How the workout was recorded (e.g. manual, auto, confirmed).",
            "start_datetime": "ISO 8601 start time of the workout.",
            "end_datetime": "ISO 8601 end time of the workout.",
        },
    },
    "heartrate": {
        "description": "Time-series heart-rate samples in beats per minute.",
        "docs_url": _DOCS,
        "columns": {
            "timestamp": "ISO 8601 timestamp of the heart-rate sample.",
            "bpm": "Heart rate in beats per minute.",
            "source": "Context the sample was measured in (awake, rest, sleep, session, live, workout).",
        },
    },
    "personal_info": {
        "description": "Static profile information for the authenticated user.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the user.",
            "age": "Age of the user in years.",
            "weight": "Weight of the user in kilograms.",
            "height": "Height of the user in metres.",
            "biological_sex": "Biological sex recorded for the user.",
            "email": "Email address associated with the Oura account.",
        },
    },
}

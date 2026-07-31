from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_COMMON_COLUMNS = {
    "id": "Unique identifier of the record.",
    "name": "Display name of the record.",
    "createdTimestamp": "When the record was created.",
    "updatedTimestamp": "When the record was last updated.",
    "isArchived": "Whether the record has been archived.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "client": {
        "description": "The OPUSWatch client (company account) the API key belongs to.",
        "columns": {
            "name": "Display name of the client account.",
            "updatedTimestamp": "When the client record was last updated.",
        },
    },
    "locations": {
        "description": "Locations or areas within the greenhouse or nursery.",
        "columns": {
            **_COMMON_COLUMNS,
            "externalId": "Identifier of the location in an external system.",
            "layoutIds": "Identifiers of the layouts defined for this location.",
        },
    },
    "rows": {
        "description": "Physical rows or sections where plants are cultivated.",
        "columns": {
            **_COMMON_COLUMNS,
            "locationId": "Identifier of the location this row belongs to.",
            "layoutId": "Identifier of the layout this row belongs to.",
            "varietyId": "Identifier of the plant variety cultivated in this row.",
            "labelIds": "Identifiers of the labels attached to this row.",
            "latestWorkerId": "Identifier of the worker who most recently worked this row.",
            "rowNumber": "Number of the row within its location.",
            "rowLength": "Length of the row.",
            "rowWidth": "Width of the row.",
            "rowFloorArea": "Floor area of the row.",
        },
    },
    "users": {
        "description": "People with access to the OPUSWatch system.",
        "columns": {
            **_COMMON_COLUMNS,
            "email": "Email address of the user.",
            "role": "Role of the user within the OPUSWatch system.",
            "language": "Preferred language of the user.",
            "associatedWorkerId": "Identifier of the worker record associated with this user.",
        },
    },
    "workers": {
        "description": "Workforce members registered in OPUSWatch.",
        "columns": {
            **_COMMON_COLUMNS,
            "workerCode": "Code identifying the worker.",
            "workerGroupId": "Identifier of the worker group this worker belongs to.",
            "externalId": "Identifier of the worker in an external system (e.g. payroll).",
            "hourlyRate": "Hourly rate of the worker.",
            "startTimestamp": "When the worker started.",
            "endTimestamp": "When the worker ended.",
            "locationIds": "Identifiers of the locations this worker is assigned to.",
            "labelIds": "Identifiers of the labels attached to this worker.",
            "leftHanded": "Whether the worker is left-handed.",
        },
    },
    "worker_groups": {
        "description": "Groupings of workers.",
        "columns": _COMMON_COLUMNS,
    },
    "tasks": {
        "description": "Tasks workers can register their work against.",
        "columns": {
            **_COMMON_COLUMNS,
            "externalId": "Identifier of the task in an external system.",
            "function": "Function of the task.",
            "taskGroupIds": "Identifiers of the task groups this task belongs to.",
            "locationIds": "Identifiers of the locations this task applies to.",
        },
    },
    "task_groups": {
        "description": "Groupings of tasks.",
        "columns": _COMMON_COLUMNS,
    },
    "labels": {
        "description": "Labels used to categorize workers, rows, and varieties.",
        "columns": _COMMON_COLUMNS,
    },
    "varieties": {
        "description": "Plant varieties cultivated at the client's locations.",
        "columns": {
            **_COMMON_COLUMNS,
            "externalId": "Identifier of the variety in an external system.",
            "assignedLocationIds": "Identifiers of the locations this variety is assigned to.",
            "labelIds": "Identifiers of the labels attached to this variety.",
        },
    },
    "registrations": {
        "description": "Individual work registrations recorded by workers on their OPUSWatch.",
        "columns": {
            "id": "Unique identifier of the registration.",
            "workerId": "Identifier of the worker who made the registration.",
            "worker": "Name of the worker who made the registration.",
            "workerGroupId": "Identifier of the worker's group.",
            "taskId": "Identifier of the task the registration is for.",
            "task": "Name of the task the registration is for.",
            "taskType": "Type of the task the registration is for.",
            "locationId": "Identifier of the location the work took place at.",
            "startTimestamp": "When the registered work started.",
            "endTimestamp": "When the registered work ended.",
            "updatedTimestamp": "When the registration was last updated.",
            "laborCost": "Labor cost of the registered work.",
            "stepCounter": "Steps counted by the watch during the registration.",
            "deviceNumber": "Number of the OPUSWatch device used.",
            "isArchived": "Whether the registration has been archived.",
        },
    },
    "sessions": {
        "description": "Work sessions with productivity metrics such as counts, performance, and labor cost.",
        "columns": {
            "id": "Unique identifier of the session.",
            "workerId": "Identifier of the worker for the session.",
            "worker": "Name of the worker for the session.",
            "rowId": "Identifier of the row worked during the session.",
            "varietyId": "Identifier of the plant variety worked during the session.",
            "locationId": "Identifier of the location the session took place at.",
            "startTimestampGross": "When the session started, including breaks.",
            "endTimestampGross": "When the session ended, including breaks.",
            "startTimestampNet": "When the session started, excluding breaks.",
            "endTimestampNet": "When the session ended, excluding breaks.",
            "updatedTimestamp": "When the session was last updated.",
            "count": "Units counted during the session.",
            "correctedCount": "Corrected unit count for the session.",
            "performanceGross": "Performance over the gross session duration.",
            "performanceNet": "Performance over the net session duration.",
            "laborCost": "Labor cost of the session.",
            "deviceNumber": "Number of the OPUSWatch device used.",
            "isArchived": "Whether the session has been archived.",
        },
    },
}

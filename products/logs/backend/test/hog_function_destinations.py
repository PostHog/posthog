from typing import Any, cast
from uuid import UUID

from django.db import transaction

from products.alerts.backend.facade.destinations import (
    create_alert_destination_hog_functions,
    list_alert_destination_groups,
)
from products.alerts_platform.backend.facade.api import record_source_destination
from products.alerts_platform.backend.facade.contracts import AlertDestinationData
from products.logs.backend.alert_destinations import (
    LOGS_ALERT_EVENT_IDS,
    build_logs_destination_configs,
    logs_destination_event_kinds,
    row_event_kinds,
)
from products.logs.backend.presentation.views.alerts_api import LogsAlertCreateDestinationSerializer


def add_hog_function_destination(
    *, team_id: int, user_id: int, alert_id: str, payload: dict[str, Any], alert_name: str = "Errors"
) -> list[str]:
    """A destination stored the way logs alerts stored one before creates wrote only a row: stock
    HogFunctions, one per event kind, and the `AlertDestination` row that copies them. Such destinations
    stay on HogFunctions until the conversion command moves them, or when someone customizes one."""
    serializer = LogsAlertCreateDestinationSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    data = cast(AlertDestinationData, serializer.validated_data)
    with transaction.atomic():
        hog_function_ids = create_alert_destination_hog_functions(
            build_logs_destination_configs(alert_id=alert_id, alert_name=alert_name, data=data),
            team_id=team_id,
            created_by_id=user_id,
            alert_id=alert_id,
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
        )
        record_source_destination(
            team_id=team_id,
            public_id=UUID(alert_id),
            data=data,
            event_kinds=row_event_kinds(logs_destination_event_kinds(data["type"])),
            hog_function_ids=hog_function_ids,
            hog_function_groups=list_alert_destination_groups(
                team_id=team_id, alert_id=alert_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS
            ),
        )
    return [str(hog_function_id) for hog_function_id in hog_function_ids]

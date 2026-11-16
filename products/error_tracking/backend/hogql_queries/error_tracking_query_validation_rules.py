from rest_framework.exceptions import ValidationError

from posthog.schema import ErrorTrackingQuery

from posthog.hogql_queries.validation.validation import QueryValidationContext

from products.error_tracking.backend.facade.query_utils import VOLUME_RESOLUTION_MAX


class ValidateVolumeResolution:
    code = "error_tracking_volume_resolution_out_of_range"

    def validate(self, context: QueryValidationContext[ErrorTrackingQuery]) -> None:
        if not 0 <= context.query.volumeResolution <= VOLUME_RESOLUTION_MAX:
            raise ValidationError(
                f"Use an integer bucket count from 0 to {VOLUME_RESOLUTION_MAX} for volumeResolution.",
                code=self.code,
            )

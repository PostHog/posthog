import { LemonTag, Spinner } from '@posthog/lemon-ui'

import type { JourneyRunStatusEnumApi } from '../generated/api.schemas'
import { RUN_STATUS_LABELS, RUN_STATUS_TAG_TYPES, isRunActive } from '../journeyRuns'

export function JourneyRunStatusTag({ status }: { status: JourneyRunStatusEnumApi }): JSX.Element {
    return (
        <LemonTag
            type={RUN_STATUS_TAG_TYPES[status]}
            icon={isRunActive(status) ? <Spinner textColored /> : undefined}
            data-attr="user-journey-run-status"
        >
            {RUN_STATUS_LABELS[status]}
        </LemonTag>
    )
}

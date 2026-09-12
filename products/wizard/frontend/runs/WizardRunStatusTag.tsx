import { IconCheckCircle, IconClock, IconX, IconXCircle } from '@posthog/icons'
import { Badge, Spinner } from '@posthog/quill-primitives'

import type { WizardRunApi } from '../generated/api.schemas'

export function WizardRunStatusTag({ status }: { status: WizardRunApi['status'] }): JSX.Element {
    if (status === 'completed') {
        return (
            <Badge variant="success">
                <IconCheckCircle />
                Completed
            </Badge>
        )
    }

    if (status === 'failed') {
        return (
            <Badge variant="destructive">
                <IconXCircle />
                Failed
            </Badge>
        )
    }

    if (status === 'running') {
        return (
            <Badge variant="warning">
                <Spinner />
                Running
            </Badge>
        )
    }

    if (status === 'cancelled') {
        return (
            <Badge variant="default">
                <IconX />
                Canceled
            </Badge>
        )
    }

    return (
        <Badge variant="warning">
            <IconClock />
            Starting
        </Badge>
    )
}

import { IconCheckCircle, IconClock, IconX, IconXCircle } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import type { WizardRunApi } from '../generated/api.schemas'

export function WizardRunStatusTag({ status }: { status: WizardRunApi['status'] }): JSX.Element {
    if (status === 'completed') {
        return (
            <LemonTag type="success" size="medium" icon={<IconCheckCircle />}>
                Completed
            </LemonTag>
        )
    }

    if (status === 'failed') {
        return (
            <LemonTag type="danger" size="medium" icon={<IconXCircle />}>
                Failed
            </LemonTag>
        )
    }

    if (status === 'running') {
        return (
            <LemonTag type="warning" size="medium" icon={<Spinner textColored />}>
                Running
            </LemonTag>
        )
    }

    if (status === 'cancelled') {
        return (
            <LemonTag type="muted" size="medium" icon={<IconX />}>
                Canceled
            </LemonTag>
        )
    }

    return (
        <LemonTag type="warning" size="medium" icon={<IconClock />}>
            Starting
        </LemonTag>
    )
}

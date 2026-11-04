import { IconCheckCircle, IconClock, IconXCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import type { WizardRunApi } from '../../generated/api.schemas'

export function WizardRunStatusIcon({ status }: { status: WizardRunApi['status'] }): JSX.Element {
    if (status === 'completed') {
        return <IconCheckCircle className="text-success" />
    }
    if (status === 'failed' || status === 'cancelled') {
        return <IconXCircle className="text-danger" />
    }
    if (status === 'running') {
        return <Spinner textColored />
    }
    return <IconClock className="text-muted" />
}

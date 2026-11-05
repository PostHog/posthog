import { IconCheckCircle, IconClock, IconXCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import type { WizardRunProgressState } from '../../lib/wizardRunDisplay'

export function WizardRunProgressStateIcon({ state }: { state: WizardRunProgressState }): JSX.Element {
    if (state === 'active') {
        return <Spinner />
    }
    if (state === 'complete') {
        return <IconCheckCircle className="text-success" />
    }
    return state === 'failed' ? <IconXCircle className="text-danger" /> : <IconClock className="text-muted" />
}

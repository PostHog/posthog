import { LemonTag } from '@posthog/lemon-ui'

import type { VisionAlertConfigurationApi } from '../../generated/api.schemas'

export function ScannerAlertStateTag({ alert }: { alert: VisionAlertConfigurationApi }): JSX.Element {
    if (!(alert.enabled ?? true)) {
        return <LemonTag type="muted">Disabled</LemonTag>
    }
    if (alert.kind === 'match') {
        return <LemonTag type="success">Active</LemonTag>
    }
    switch (alert.state) {
        case 'firing':
            return <LemonTag type="danger">Firing</LemonTag>
        case 'snoozed':
            return <LemonTag type="warning">Snoozed</LemonTag>
        case 'errored':
            return <LemonTag type="warning">Errored</LemonTag>
        case 'broken':
            return <LemonTag type="danger">Broken</LemonTag>
        default:
            return <LemonTag type="success">Not firing</LemonTag>
    }
}

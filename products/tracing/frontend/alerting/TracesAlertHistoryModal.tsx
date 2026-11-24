import { LemonModal } from '@posthog/lemon-ui'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { TracesAlertEventHistory } from './TracesAlertEventHistory'

export function TracesAlertHistoryModal({
    alert,
    onClose,
}: {
    alert: PlatformAlertConfigurationApi | null
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} title={alert ? `${alert.name} history` : ''} width={900}>
            {alert ? <TracesAlertEventHistory alert={alert} /> : null}
        </LemonModal>
    )
}

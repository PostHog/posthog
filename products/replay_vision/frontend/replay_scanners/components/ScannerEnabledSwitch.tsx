import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScanner } from '../types'

/** The single enable/disable control for a scanner, shared by every surface that shows a scanner. */
export function ScannerEnabledSwitch({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { togglingEnabled } = useValues(replayScannerLogic({ id: scanner.id }))
    const { toggleEnabled } = useActions(replayScannerLogic({ id: scanner.id }))

    return (
        <LemonSwitch
            checked={scanner.enabled}
            onChange={() => toggleEnabled()}
            loading={togglingEnabled}
            bordered
            size="small"
            label={scanner.enabled ? 'Enabled' : 'Disabled'}
            tooltip={scanner.enabled ? 'Runs automatically on a schedule' : 'Runs on-demand only'}
            disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
            data-attr="vision-scanner-toggle-enabled"
            data-ph-capture-attribute-scanner-type={scanner.scanner_type}
            data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
        />
    )
}

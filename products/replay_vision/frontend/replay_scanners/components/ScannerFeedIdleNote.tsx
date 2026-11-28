import { LemonButton } from '@posthog/lemon-ui'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import type { ReplayScanner } from '../types'
import { useScannerSave } from '../useScannerSave'
import { HighlightFeedNote } from './HighlightFeedNote'

export function ScannerFeedIdleNote({
    scanner,
    kind,
    onSaved,
}: {
    scanner: ReplayScanner
    kind: 'off' | 'starting'
    onSaved: () => void
}): JSX.Element {
    const { turnOn, saving } = useScannerSave(scanner.id, onSaved)

    if (kind === 'starting') {
        return (
            <HighlightFeedNote>
                <span>The first scan is in progress. Highlights show up here as it finds them.</span>
            </HighlightFeedNote>
        )
    }
    return (
        <HighlightFeedNote>
            <span>This scanner is off, so it isn't finding new sessions.</span>
            <LemonButton
                type="secondary"
                size="small"
                loading={saving}
                onClick={() => void turnOn()}
                disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                data-attr="vision-home-scanner-turn-on"
            >
                Turn on
            </LemonButton>
        </HighlightFeedNote>
    )
}

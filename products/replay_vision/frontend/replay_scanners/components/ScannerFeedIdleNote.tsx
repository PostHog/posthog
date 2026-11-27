import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { saveScannerEnabled } from '../saveScannerEnabled'
import type { ReplayScanner } from '../types'
import { HighlightFeedNote } from './HighlightFeedNote'

export function ScannerFeedIdleNote({
    scanner,
    kind,
}: {
    scanner: ReplayScanner
    kind: 'off' | 'starting'
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { loadScanners } = useActions(visionScannersListLogic)
    const [turningOn, setTurningOn] = useState(false)

    if (kind === 'starting') {
        return (
            <HighlightFeedNote>
                <span>The first scan is in progress. Highlights show up here as it finds them.</span>
            </HighlightFeedNote>
        )
    }
    const turnOn = async (): Promise<void> => {
        if (!currentTeamId) {
            return
        }
        setTurningOn(true)
        try {
            if (await saveScannerEnabled(String(currentTeamId), scanner.id, true)) {
                loadScanners()
            }
        } catch (error: any) {
            lemonToast.error(
                `Couldn't turn on the scanner${error?.detail ? `: ${error.detail}` : ''}. Try again from its settings.`
            )
        } finally {
            setTurningOn(false)
        }
    }
    return (
        <HighlightFeedNote>
            <span>This scanner is off, so it isn't finding new sessions.</span>
            <LemonButton
                type="secondary"
                size="small"
                loading={turningOn}
                onClick={() => void turnOn()}
                disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                data-attr="vision-home-scanner-turn-on"
            >
                Turn on
            </LemonButton>
        </HighlightFeedNote>
    )
}

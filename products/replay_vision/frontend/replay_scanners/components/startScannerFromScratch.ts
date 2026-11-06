import { combineUrl, router } from 'kea-router'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { replayScannerLogic } from '../replayScannerLogic'

/** Starts a blank scanner and opens the details step. A saved draft would be replaced, so the person
 * confirms that first. */
export function startScannerFromScratch(): void {
    const logic = replayScannerLogic({ id: 'new' })
    const start = (): void => {
        logic.actions.startFromScratch()
        router.actions.push(combineUrl(urls.replayVisionScannerDetails('new'), router.values.searchParams).url)
    }
    if (logic.values.scannerDraftSavedAt === null) {
        start()
        return
    }
    LemonDialog.open({
        title: 'Start over and lose your draft?',
        description: 'The scanner you have in progress will be replaced by a blank one.',
        primaryButton: { children: 'Start over', status: 'danger', onClick: start },
        secondaryButton: { children: 'Keep my draft' },
    })
}

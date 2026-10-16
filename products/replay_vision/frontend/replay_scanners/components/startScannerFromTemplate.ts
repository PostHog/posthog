import { combineUrl, router } from 'kea-router'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'

import { replayScannerLogic } from '../replayScannerLogic'
import { scannerStartSearchParams } from './scannerStartParams'

/** Starts a new scanner from a template, or from scratch when `templateKey` is null, and opens the
 * details step. A saved draft would be replaced, so the person confirms that first. */
export function startScannerFromTemplate(templateKey: string | null): void {
    const logic = replayScannerLogic({ id: 'new' })
    const start = (): void => {
        logic.actions.startFromTemplate(templateKey)
        router.actions.push(
            combineUrl(
                urls.replayVisionScannerDetails('new'),
                scannerStartSearchParams(router.values.searchParams, templateKey)
            ).url
        )
    }
    if (logic.values.scannerDraftSavedAt === null) {
        start()
        return
    }
    LemonDialog.open({
        title: 'Start over and lose your draft?',
        description: templateKey
            ? 'The scanner you have in progress will be replaced by this template.'
            : 'The scanner you have in progress will be replaced by a blank one.',
        primaryButton: { children: 'Start over', status: 'danger', onClick: start },
        secondaryButton: { children: 'Keep my draft' },
    })
}

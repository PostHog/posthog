import { useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { replayScannerLogic } from '../replayScannerLogic'

/** Tells the person building a new scanner that each edit is already kept in the draft, and where
 * the scanner itself gets created, since the wizard has no save button of its own. */
export function ScannerDraftStatus({
    scannerId,
    fromOverview,
}: {
    scannerId: string
    fromOverview: boolean
}): JSX.Element | null {
    const { hasUnsavedChanges, scannerDraftSavedAt } = useValues(replayScannerLogic({ id: scannerId }))

    if (scannerId !== 'new' || !hasUnsavedChanges) {
        return null
    }

    const createHint = fromOverview
        ? 'The scanner is created from the overview.'
        : 'The scanner is created on the last step.'

    // The draft is written on every change, so a missing timestamp while the form is dirty means
    // the browser refused the write (private mode, full storage) and the edits live in memory only.
    if (scannerDraftSavedAt === null) {
        return (
            <Tooltip
                title={`Your browser couldn't store the draft, so leaving this page loses the edits. ${createHint}`}
            >
                <span
                    className="flex items-center gap-1 text-xs text-warning cursor-default"
                    data-attr="vision-editor-draft-status"
                    data-ph-capture-attribute-draft-status="not_saved"
                >
                    <IconWarning className="text-base shrink-0" />
                    Draft not saved
                </span>
            </Tooltip>
        )
    }

    return (
        <Tooltip
            title={`Saved at ${dayjs(scannerDraftSavedAt).format('LTS')}. Every edit is kept in this draft. ${createHint}`}
        >
            <span
                className="flex items-center gap-1 text-xs text-secondary cursor-default"
                data-attr="vision-editor-draft-status"
                data-ph-capture-attribute-draft-status="saved"
            >
                <IconCheckCircle className="text-base text-success shrink-0" />
                Draft saved
            </span>
        </Tooltip>
    )
}

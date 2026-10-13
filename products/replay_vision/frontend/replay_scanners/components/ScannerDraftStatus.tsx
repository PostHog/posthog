import { useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { replayScannerLogic } from '../replayScannerLogic'

export function ScannerDraftStatus({
    scannerId,
    fromOverview,
}: {
    scannerId: string
    fromOverview: boolean
}): JSX.Element | null {
    const { isNew, hasUnsavedChanges, scannerDraftSavedAt } = useValues(replayScannerLogic({ id: scannerId }))

    if (!isNew || !hasUnsavedChanges) {
        return null
    }

    const createHint = fromOverview
        ? 'The scanner is created from the overview.'
        : 'The scanner is created on the last step.'

    // Dirty form without a timestamp: the browser refused the draft write.
    if (scannerDraftSavedAt === null) {
        return (
            <Tooltip
                title={`Your browser couldn't store the draft, so leaving the editor loses the edits. ${createHint}`}
            >
                <span
                    className="flex items-center gap-1 text-xs text-warning cursor-default"
                    data-attr="vision-editor-draft-status"
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
            >
                <IconCheckCircle className="text-base text-success shrink-0" />
                Draft saved
            </span>
        </Tooltip>
    )
}

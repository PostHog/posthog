import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getScoutCreateDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { featuredScoutTemplateKey, ROOT_CAUSE_MIN_SESSIONS } from '../scannerScout'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { ScannerScoutFormModal } from './ScannerScoutFormModal'

/** Offers a root cause scout next to the scanner's results, until the scanner has one or the person
 * hides the offer. */
export function RootCausePrompt({
    scannerId,
    scannedSessions,
}: {
    scannerId: string
    /** Below the scout's minimum it can't name a cause, so the offer waits for enough results. */
    scannedSessions: number
}): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerName = scanner?.name || ''
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const { scoutConfigs, rootCauseScout, rootCausePromptDismissed, createTemplateKey } = useValues(logic)
    const { openCreateModal, dismissRootCausePrompt } = useActions(logic)

    // Without the roster the prompt can't tell whether the scanner already has a root cause scout.
    if (
        !scanner ||
        scoutConfigs === null ||
        rootCauseScout ||
        rootCausePromptDismissed ||
        scannedSessions < ROOT_CAUSE_MIN_SESSIONS ||
        featuredScoutTemplateKey(scanner.scanner_type) !== 'root-cause'
    ) {
        return null
    }
    return (
        <div
            className="flex items-center justify-between gap-4 rounded border border-dashed px-3 py-2"
            data-attr="vision-root-cause-prompt"
        >
            <div className="flex min-w-0 flex-1 items-start gap-2">
                <IconSparkles className="mt-0.5 size-4 shrink-0 text-ai" />
                <div className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium">Find out what's behind these results</span>
                    <span className="text-xs text-secondary">
                        A weekly scout groups the scanner's findings into causes and links to the recordings behind
                        each.
                    </span>
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => openCreateModal('root-cause')}
                    disabledReason={getScoutCreateDisabledReason(scanner.user_access_level)}
                    data-attr="vision-root-cause-prompt-create"
                >
                    Add scout
                </LemonButton>
                <LemonButton
                    size="small"
                    icon={<IconX />}
                    onClick={dismissRootCausePrompt}
                    tooltip="Hide for this scanner"
                    data-attr="vision-root-cause-prompt-dismiss"
                />
            </div>
            {createTemplateKey === 'root-cause' && (
                <ScannerScoutFormModal key="root-cause" scannerId={scannerId} scannerName={scannerName} />
            )}
        </div>
    )
}

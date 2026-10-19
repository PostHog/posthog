import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { getScoutCreateDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerOverviewLogic } from '../scannerOverviewLogic'
import { hasRootCauseTemplate, ROOT_CAUSE_MIN_SESSIONS } from '../scannerScout'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { ScannerScoutFormModal } from './ScannerScoutFormModal'

/** Offers a root cause scout next to the scanner's results, until the scanner has one or the person
 * hides the offer. */
export function RootCausePrompt({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerName = scanner?.name || ''
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const { scoutConfigs, rootCauseScout, createTemplateKey } = useValues(logic)
    const { openCreateModal } = useActions(logic)
    const { monitorStats, classifierTagStats, scorerSummary } = useValues(scannerOverviewLogic({ scannerId }))
    // pinned: dismissKey is stored in localStorage, so renaming it brings back every dismissed prompt.
    const dismissal = lemonBannerLogic({ dismissKey: `vision-root-cause-prompt-${scannerId.toLowerCase()}` })
    const { isDismissed } = useValues(dismissal)
    const { dismiss } = useActions(dismissal)

    // Without the roster the prompt can't tell whether the scanner already has a root cause scout.
    // Mirrors the template's bucket per type: yes verdicts, the largest category, the worst quarter of scores.
    const explainedSessions =
        scanner?.scanner_type === 'monitor'
            ? monitorStats.yesTotal
            : scanner?.scanner_type === 'classifier'
              ? (classifierTagStats.fixedRanked[0]?.[1] ?? 0)
              : Math.floor((scorerSummary?.count ?? 0) / 4)
    // Rendered whatever the gates say: a roster or stats refresh can hide the prompt while the form is
    // open, and unmounting it then would drop the draft and leave the create key set.
    const form =
        createTemplateKey === 'root-cause' ? (
            <ScannerScoutFormModal scannerId={scannerId} scannerName={scannerName} />
        ) : null
    if (
        !scanner ||
        scoutConfigs === null ||
        rootCauseScout ||
        isDismissed ||
        // Below the scout's minimum it can't name a cause, so the offer waits until the sessions it
        // would explain reach it.
        explainedSessions < ROOT_CAUSE_MIN_SESSIONS ||
        !hasRootCauseTemplate(scanner.scanner_type)
    ) {
        return form
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
                    onClick={dismiss}
                    tooltip="Hide for this scanner"
                    data-attr="vision-root-cause-prompt-dismiss"
                />
            </div>
            {form}
        </div>
    )
}

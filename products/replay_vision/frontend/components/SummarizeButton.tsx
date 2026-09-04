import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconLogomark, IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AccessControlLevel } from '~/types'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { BUILT_IN_SUMMARY_LABEL } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'

/** Runs whichever summarizer `resolveSummarizer` settles on, and lets the user pick another. */
export function SummarizeButton({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizing, defaultSummarizer, summarizerScanners } = useValues(logic)
    const { summarize, summarizeWith } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)
    // `loading` only disables the button itself. The caret and the menu rows are their own buttons, so
    // without this a second summarizer is one click away mid-run, and it spends the quota again.
    const inFlightDisabledReason = summarizing ? 'A summary is already running' : null
    // Both paths are scanner writes: an inline scan mints a scanner, and `observe` is a write action on
    // the scanner it runs. Each also exposes recording contents, so both need recording read as well.
    const builtInDisabledReason = inFlightDisabledReason ?? getReplayVisionEditDisabledReason() ?? quotaDisabledReason
    // Object-level, so a scanner this user cannot edit is disabled rather than answering with a 403.
    const scannerDisabledReason = (scanner: ReplayScannerApi): string | null | undefined =>
        inFlightDisabledReason ??
        getReplayVisionEditDisabledReason(scanner.user_access_level as AccessControlLevel | null) ??
        quotaDisabledReason
    // Nobody could tell which summarizer the button used, so it says so.
    const label = defaultSummarizer ? `Summarize with ${defaultSummarizer.name}` : 'Summarize this recording'
    const summarizerTooltip = defaultSummarizer
        ? `Runs your "${defaultSummarizer.name}" scanner on this recording.`
        : 'Writes a summary using a built-in prompt.'

    const menuItems: LemonMenuItem[] = [
        ...summarizerScanners.map((scanner) => ({
            key: scanner.id,
            label: scanner.name,
            active: scanner.id === defaultSummarizer?.id,
            disabledReason: scannerDisabledReason(scanner),
            onClick: () => summarizeWith(scanner.id),
            'data-attr': 'vision-summarize-pick-scanner',
        })),
        {
            key: 'built-in',
            // Every other row is a scanner the team owns and can open. This one is PostHog's, so it
            // carries the logomark and says so, rather than reading as a scanner they cannot find.
            label: (
                <span className="flex items-center justify-between gap-2 w-full">
                    <span className="truncate">{BUILT_IN_SUMMARY_LABEL}</span>
                    <span className="flex items-center gap-1.5 text-xs shrink-0">
                        <IconLogomark className="text-base text-primary" />
                        <span className="text-muted">Built in</span>
                    </span>
                </span>
            ),
            tooltip: 'Uses a built-in prompt. Nothing is saved to your scanners, so there is nothing to open or edit.',
            active: !defaultSummarizer,
            disabledReason: builtInDisabledReason,
            onClick: () => summarizeWith(null),
            'data-attr': 'vision-summarize-pick-built-in',
        },
    ]

    const button = (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconNotebook />}
            loading={summarizing}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => (dataProcessingAccepted ? summarize() : setConsentRequested(true))}
            disabledReason={defaultSummarizer ? scannerDisabledReason(defaultSummarizer) : builtInDisabledReason}
            tooltip={quotaTooltip ?? summarizerTooltip}
            data-attr="vision-summarize-recording"
            data-ph-capture-attribute-summarizer={defaultSummarizer ? 'configured' : 'built-in'}
            // The dropdown is the only way to reach a second summarizer, so it appears once one exists.
            sideAction={
                summarizerScanners.length > 0 && dataProcessingAccepted
                    ? {
                          icon: <IconChevronDown />,
                          dropdown: { placement: 'bottom-end', overlay: <LemonMenuOverlay items={menuItems} /> },
                          divider: false,
                          disabledReason: inFlightDisabledReason,
                          'aria-label': 'Choose a summarizer',
                          'data-attr': 'vision-summarize-choose',
                      }
                    : null
            }
        >
            <span className="truncate">{dataProcessingAccepted ? label : 'Allow AI analysis and summarize'}</span>
        </LemonButton>
    )

    if (dataProcessingAccepted) {
        return button
    }

    return (
        <AIConsentPopoverWrapper
            placement="bottom-end"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                summarize()
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
    )
}

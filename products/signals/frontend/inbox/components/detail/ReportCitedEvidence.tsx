import { useMemo } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { SignalCard } from '../../SignalCard'
import type { SignalReport } from '../../types'
import { citedReportEvidence } from '../../utils/reportEvidence'

export function ReportCitedEvidence({
    markdown,
    signals,
    report,
}: {
    markdown: string
    signals: SignalNodeApi[]
    report: SignalReport
}): JSX.Element | null {
    const projectUrl = `${window.location.origin}${addProjectIdIfMissing('/')}`
    const cited = useMemo(() => citedReportEvidence(markdown, signals, projectUrl), [markdown, signals, projectUrl])
    if (!cited.length) {
        return null
    }
    return (
        <LemonDropdown
            placement="bottom-start"
            closeOnClickInside={false}
            onVisibilityChange={(visible) => {
                if (visible) {
                    captureInboxReportAction({
                        report,
                        actionType: 'expand_section',
                        surface: 'detail_pane',
                        extra: { section: 'cited_evidence' },
                    })
                }
            }}
            overlay={
                <div
                    className="w-96 max-w-full flex flex-col gap-2"
                    onClickCapture={(event) => {
                        if (event.target instanceof Element && event.target.closest('a')) {
                            captureInboxReportAction({
                                report,
                                actionType: 'open_evidence_source',
                                surface: 'detail_pane',
                            })
                        }
                    }}
                >
                    <span className="text-xs text-secondary">Sources linked in this section</span>
                    {cited.map((signal) => (
                        <SignalCard key={signal.signal_id} signal={signal} />
                    ))}
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconSearch />}
                className="w-fit"
                data-attr="inbox-report-cited-evidence"
            >
                View cited evidence ({cited.length})
            </LemonButton>
        </LemonDropdown>
    )
}

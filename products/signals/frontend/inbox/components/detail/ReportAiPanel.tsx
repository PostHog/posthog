import { useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ReportDiscussionComposer } from './ReportDiscussionComposer'

export function ReportAiPanel({ panelId }: { panelId: string }): JSX.Element {
    const { reportChatContext } = useValues(inboxTaskKickoffLogic)
    const report = reportChatContext?.report
    useAttachedContext(
        report
            ? [{ type: 'signal_report', key: report.id, label: `Report: ${report.title || 'Untitled report'}` }]
            : null
    )

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0">
            <SidePanelRunner
                panelId={panelId}
                composer={
                    reportChatContext ? (
                        <ReportDiscussionComposer key={reportChatContext.report.id} {...reportChatContext} />
                    ) : (
                        // `reportChatContext` is in-memory, but the `inbox-report` panel option round-trips
                        // through the URL hash, so a reload lands here knowing the panel is a report chat but
                        // not which report. Always filling the composer slot is what keeps the runner's
                        // generic task composer out: a send from that would spend a run on a question the
                        // agent cannot tie to any report.
                        <EmptyMessage
                            title="No report selected"
                            description="Reloading the page clears which report this chat was about. Select Ask AI on the report to start a new chat."
                        />
                    )
                }
            />
        </div>
    )
}

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
            ? [
                  {
                      type: 'signal_report',
                      key: report.id,
                      label: `Report: ${report.title || 'Untitled report'}`,
                      dismissible: false,
                  },
              ]
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
                        // The `inbox-report` panel option round-trips through the URL hash, so the panel can
                        // open on a page with no report to restore. Always filling the composer slot is what
                        // keeps the runner's generic task composer out: a send from that would spend a run on
                        // a question the agent cannot tie to any report.
                        <EmptyMessage
                            title="No report selected"
                            description="Open a report and select Ask AI to chat about it."
                        />
                    )
                }
            />
        </div>
    )
}

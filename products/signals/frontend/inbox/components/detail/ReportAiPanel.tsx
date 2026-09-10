import { useValues } from 'kea'

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
                    ) : undefined
                }
            />
        </div>
    )
}

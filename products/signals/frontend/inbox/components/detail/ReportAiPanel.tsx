import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

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
            {report && (
                <div className="border-b border-primary p-3 min-w-0">
                    <span className="text-xs text-secondary">Report in this chat</span>
                    <LemonButton type="tertiary" size="small" to={urls.inboxReport('reports', report.id)} fullWidth>
                        <span className="whitespace-normal text-left">{report.title || 'Untitled report'}</span>
                    </LemonButton>
                </div>
            )}
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

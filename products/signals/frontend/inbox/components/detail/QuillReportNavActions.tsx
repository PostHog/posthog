import { useActions, useValues } from 'kea'

import { IconCopy, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { reportWorkKind, reportWorkPrompt } from 'scenes/project-homepage/today/todayNextStep'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'

/** The two ways to take a report to an AI: copy it as a prompt, or ask PostHog AI here. */
export function QuillReportNavActions({ report }: { report: SignalReport }): JSX.Element {
    const logic = todayReportLogic({ reportId: report.id })
    const { reportUrl, composerOpen } = useValues(logic)
    const { openComposer } = useActions(logic)
    const { phoneLayout } = useValues(todayShellLogic)

    const copyPrompt = (): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'detail_pane',
            extra: { agent: 'clipboard', work: reportWorkKind(report) },
        })
        void copyToClipboard(reportWorkPrompt(report, reportUrl), 'prompt for your agent')
    }

    return (
        <>
            <Button
                variant="link-muted"
                size={phoneLayout ? 'icon-sm' : 'sm'}
                onClick={copyPrompt}
                aria-label="Copy prompt"
                tooltip="Copy this report as a prompt for your own AI agent"
                data-attr="inbox-report-copy-prompt"
            >
                <IconCopy />
                {!phoneLayout && 'Copy prompt'}
            </Button>
            <Button
                variant="link-muted"
                size={phoneLayout ? 'icon-sm' : 'sm'}
                onClick={() => openComposer()}
                aria-label="Ask about it"
                aria-expanded={composerOpen}
                tooltip="Ask PostHog AI about this report"
                data-attr="inbox-report-ask"
            >
                <IconSparkles />
                {!phoneLayout && 'Ask about it'}
            </Button>
        </>
    )
}

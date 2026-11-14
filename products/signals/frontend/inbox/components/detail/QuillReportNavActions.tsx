import { useValues } from 'kea'

import { IconChevronDown, IconCopy } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { reportWorkKind, reportWorkPrompt } from 'scenes/project-homepage/today/todayNextStep'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { reportMarkdown } from '../../utils/reportMarkdown'

/** The ways to take a report out of PostHog: as a prompt for an AI agent, or as markdown. */
export function QuillReportNavActions({ report }: { report: SignalReport }): JSX.Element {
    const { reportUrl } = useValues(todayReportLogic({ reportId: report.id }))
    const { phoneLayout } = useValues(todayShellLogic)

    const copy = (format: 'prompt' | 'markdown'): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'detail_pane',
            extra: { agent: 'clipboard', work: reportWorkKind(report), format },
        })
        if (format === 'prompt') {
            void copyToClipboard(reportWorkPrompt(report, reportUrl), 'prompt for your agent')
        } else {
            void copyToClipboard(reportMarkdown(report, reportUrl), 'report as markdown')
        }
    }

    return (
        <span className="flex items-center">
            {!phoneLayout && (
                <Button
                    variant="link-muted"
                    size="sm"
                    onClick={() => copy('prompt')}
                    tooltip="Copy this report as a prompt for your own AI agent"
                    data-attr="inbox-report-copy-prompt"
                >
                    <IconCopy />
                    Copy prompt
                </Button>
            )}
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="link-muted"
                            size="icon-sm"
                            aria-label="Copy options"
                            tooltip="Copy options"
                            data-attr="inbox-report-copy-options"
                        />
                    }
                >
                    {phoneLayout ? <IconCopy /> : <IconChevronDown />}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {phoneLayout && (
                        <DropdownMenuItem onClick={() => copy('prompt')} data-attr="inbox-report-copy-prompt">
                            Copy prompt
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onClick={() => copy('markdown')} data-attr="inbox-report-copy-markdown">
                        Copy as markdown
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </span>
    )
}

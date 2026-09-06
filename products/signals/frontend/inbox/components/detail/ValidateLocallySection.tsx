import { IconCopy, IconTerminal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

/** What lands on the clipboard: the report's prompt, then the link so the agent can read the report itself. */
export function validationPromptClipboardText(prompt: string, reportUrl: string): string {
    return `${prompt.trim()}\n\nThe PostHog report this came from: ${reportUrl}`
}

interface ValidateLocallySectionProps {
    report: SignalReport
    /** Absolute URL of this report, appended to the copied prompt. */
    reportUrl: string
}

/**
 * The prompt a reader pastes into a coding agent on their own machine to reproduce the finding and
 * test a fix. Report-only: the backend keeps it off the implementation PR because the steps that
 * make a finding reproducible often name internal hosts and tools, and the PR's repository is
 * usually public. Collapsed by default, so it waits for the reader who wants to check the work.
 */
export function ValidateLocallySection({ report, reportUrl }: ValidateLocallySectionProps): JSX.Element | null {
    const prompt = report.validation_prompt?.trim()
    if (!prompt) {
        return null
    }

    const copy = (): void => {
        captureInboxReportAction({ report, actionType: 'copy_validation_prompt', surface: 'detail_pane' })
        void copyToClipboard(validationPromptClipboardText(prompt, reportUrl), 'validation prompt')
    }

    return (
        <DetailSection
            icon={<IconTerminal />}
            title="Validate locally"
            collapsible
            defaultCollapsed
            rightSlot={
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconCopy />}
                    onClick={copy}
                    data-attr="inbox-report-copy-validation-prompt"
                >
                    Copy prompt
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-2">
                <p className="m-0 text-xs text-tertiary">
                    Paste this into a coding agent on your machine to recreate the finding and test a fix.
                </p>
                <pre className="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded border border-primary bg-surface-secondary p-3 text-xs text-secondary">
                    {prompt}
                </pre>
            </div>
        </DetailSection>
    )
}

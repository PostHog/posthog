import { Text } from '@posthog/quill'

import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { hasRepoWorkflow } from './signalCardMatchers'
import { engineeringMetricLine } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Quill sibling of `EngineeringAnalyticsSignalCard` (flaky check, broken default branch, duration regression). */
export function QuillEngineeringAnalyticsSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!hasRepoWorkflow(signal.extra)) {
        return <QuillSignalCardShell signal={signal}>{null}</QuillSignalCardShell>
    }
    const { repo_owner, repo_name, workflow_name } = signal.extra
    const metric = engineeringMetricLine(signal)

    return (
        <QuillSignalCardShell signal={signal}>
            <div className="flex flex-col gap-1">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2">
                    <Text size="xs" variant="muted" render={<span />} className="break-all">
                        {`${repo_owner}/${repo_name}`}
                    </Text>
                    <Text size="xs" weight="medium" render={<span />} className="break-words">
                        {workflow_name}
                    </Text>
                </div>
                {metric && (
                    <Text size="xs" variant="muted" className="m-0">
                        {metric}
                    </Text>
                )}
            </div>

            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}
        </QuillSignalCardShell>
    )
}

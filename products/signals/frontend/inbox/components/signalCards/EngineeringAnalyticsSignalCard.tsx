import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { hasRepoWorkflow } from './signalCardMatchers'
import { engineeringMetricLine } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** Inbox card for engineering_analytics CI signals (flaky check, broken default branch, duration regression). */
export function EngineeringAnalyticsSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!hasRepoWorkflow(signal.extra)) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }
    const { repo_owner, repo_name, workflow_name } = signal.extra
    const metric = engineeringMetricLine(signal)

    return (
        <SignalCardShell signal={signal}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-tertiary">
                    {repo_owner}/{repo_name}
                </span>
                <span className="font-medium text-sm">{workflow_name}</span>
            </div>
            {metric && <div className="text-xs text-tertiary mt-1">{metric}</div>}

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
        </SignalCardShell>
    )
}

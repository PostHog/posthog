import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { EndpointExecutionFailedSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { isEndpointExecutionFailedExtra } from './signalCardMatchers'
import { endpointExecutionLinks } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** Inbox signal card for a failed endpoint execution: endpoint identity, error class, and the error message. */
export function EndpointExecutionFailedSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra: EndpointExecutionFailedSignalExtraApi | null = isEndpointExecutionFailedExtra(signal.extra)
        ? signal.extra
        : null

    if (!extra) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }

    const { endpoint_name, error_class, error_message } = extra
    const { endpointUrl, logsUrl } = endpointExecutionLinks(extra)

    return (
        <SignalCardShell signal={signal}>
            <div className="font-medium">{endpoint_name}</div>

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <div className="mt-2 text-xs font-mono text-danger">{error_class}</div>

            {error_message && (
                <div className="mt-2">
                    <CodeSnippet
                        language={Language.Text}
                        wrap
                        compact
                        maxLinesWithoutExpansion={6}
                        thing="error message"
                    >
                        {error_message}
                    </CodeSnippet>
                </div>
            )}

            <div className="flex items-center gap-3 text-xs mt-2">
                <span className="flex-1" />
                <Link to={endpointUrl} className="font-medium">
                    View endpoint
                </Link>
                <Link to={logsUrl} className="font-medium">
                    View execution logs
                </Link>
            </div>
        </SignalCardShell>
    )
}

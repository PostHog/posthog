import { Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { isEndpointExecutionFailedExtra } from './signalCardMatchers'
import { endpointExecutionLinks } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Quill sibling of `EndpointExecutionFailedSignalCard`: endpoint identity, error class, and the error message. */
export function QuillEndpointExecutionFailedSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!isEndpointExecutionFailedExtra(signal.extra)) {
        return <QuillSignalCardShell signal={signal}>{null}</QuillSignalCardShell>
    }

    const extra = signal.extra
    const { endpointUrl, logsUrl } = endpointExecutionLinks(extra)

    return (
        <QuillSignalCardShell signal={signal}>
            <Text size="xs" weight="medium" className="m-0 break-words">
                {extra.endpoint_name}
            </Text>

            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <Text size="xs" variant="destructive" className="m-0 break-words font-mono">
                {extra.error_class}
            </Text>

            {extra.error_message && (
                <CodeSnippet language={Language.Text} wrap compact maxLinesWithoutExpansion={6} thing="error message">
                    {extra.error_message}
                </CodeSnippet>
            )}

            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                <QuillSignalCardLink to={endpointUrl}>View endpoint</QuillSignalCardLink>
                <QuillSignalCardLink to={logsUrl}>View execution logs</QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}

import { IconExternal } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type {
    PgAnalyzeIssueReferenceApi,
    PgAnalyzeIssueSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'
import { safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { QuillExternalSignalCard } from './QuillExternalSignalCard'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { pgAnalyzeExternalUrl, pgAnalyzeVisibleReferences } from './signalCardParsing'
import type { SignalCardProps } from './types'

function QuillReferenceRow({ reference }: { reference: PgAnalyzeIssueReferenceApi }): JSX.Element | null {
    if (reference.name !== null) {
        const href = reference.url !== null ? safeHttpUrl(reference.url) : null
        return (
            <Text size="xs" render={<div />} className="flex min-w-0 flex-wrap items-center gap-1.5">
                {reference.kind !== null && <span className="text-muted-foreground">{reference.kind}</span>}
                {href !== null ? (
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={href} target="_blank" />}
                        className="min-w-0 font-mono"
                    >
                        <span className="truncate">{reference.name}</span>
                        <IconExternal />
                    </Button>
                ) : (
                    <span className="min-w-0 truncate font-mono">{reference.name}</span>
                )}
            </Text>
        )
    }

    if (reference.queryText !== null) {
        return (
            <CodeSnippet language={Language.SQL} wrap compact maxLinesWithoutExpansion={6}>
                {reference.queryText}
            </CodeSnippet>
        )
    }

    return null
}

export function QuillPgAnalyzeSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & PgAnalyzeIssueSignalExtraApi

    const visibleReferences = pgAnalyzeVisibleReferences(extra)
    const externalUrl = pgAnalyzeExternalUrl(extra)

    return (
        <QuillExternalSignalCard
            signal={signal}
            link={externalUrl ? { to: externalUrl, label: 'View in pganalyze' } : undefined}
        >
            <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>

            {visibleReferences.length > 0 && (
                <div className="flex flex-col gap-2 border-t border-border pt-2">
                    <Text size="xs" weight="medium" variant="muted" className="m-0">
                        References
                    </Text>
                    {visibleReferences.map((reference, index) => (
                        <QuillReferenceRow key={index} reference={reference} />
                    ))}
                </div>
            )}
        </QuillExternalSignalCard>
    )
}

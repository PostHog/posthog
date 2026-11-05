import { BindLogic, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { Skeleton, Text } from '@posthog/quill'

import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueListRow } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'

import { inboxErrorTrackingIssueLogic } from './inboxErrorTrackingIssueLogic'
import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { isErrorTrackingExtra } from './signalCardMatchers'
import { errorTrackingIssueLogicProps } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Footer link out to the full error tracking issue scene. */
function QuillViewIssueLink({ issueId, fingerprint }: { issueId: string; fingerprint: string }): JSX.Element {
    return (
        <QuillSignalCardLink to={urls.errorTrackingIssue(issueId, { fingerprint })} newTab>
            View issue
            <IconExternal />
        </QuillSignalCardLink>
    )
}

/** Inner body: reads the loaded issue from the bound logic and renders the live row, skeleton, or fallback. */
function QuillErrorTrackingSignalCardBody({
    signal,
    fingerprint,
}: {
    signal: SignalNode
    fingerprint: string
}): JSX.Element {
    const { mergedIssue, issueLoading, summaryLoading, mergedFailed, mergedToIssueId } =
        useValues(inboxErrorTrackingIssueLogic)

    const linkIssueId = mergedToIssueId ?? signal.source_id

    if (mergedFailed) {
        // Issue not found or merged away – degrade to a thin fallback with just the fingerprint and a link.
        return (
            <div className="flex min-w-0 items-center gap-2">
                <Text size="xs" variant="muted" render={<span />} className="min-w-0 flex-1 truncate font-mono">
                    {fingerprint}
                </Text>
                <QuillViewIssueLink issueId={linkIssueId} fingerprint={fingerprint} />
            </div>
        )
    }

    if (!mergedIssue || (issueLoading && summaryLoading)) {
        return <Skeleton className="h-16 w-full" />
    }

    return (
        <div className="overflow-hidden rounded-md border border-border bg-background">
            <ErrorTrackingIssueListRow issue={mergedIssue} canMutateIssues={false} />
        </div>
    )
}

/** Quill sibling of `ErrorTrackingSignalCard`: embeds the live issue row read-only. */
export function QuillErrorTrackingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const fingerprint = isErrorTrackingExtra(signal.extra) ? signal.extra.fingerprint : ''
    const logicProps = errorTrackingIssueLogicProps(signal, fingerprint)

    return (
        <QuillSignalCardShell signal={signal}>
            {signal.content && (
                // The signal content ends with the issue's full stack trace in a code fence, which
                // is written for the report LLM rather than for display, so cap it to keep it from
                // swallowing the evidence rail. The View issue link carries the full trace.
                <QuillSignalCardMarkdown codeMaxLines={3}>{signal.content}</QuillSignalCardMarkdown>
            )}

            <BindLogic logic={inboxErrorTrackingIssueLogic} props={logicProps}>
                <QuillErrorTrackingSignalCardBody signal={signal} fingerprint={fingerprint} />
            </BindLogic>

            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                <QuillViewIssueLink issueId={signal.source_id} fingerprint={fingerprint} />
            </div>
        </QuillSignalCardShell>
    )
}

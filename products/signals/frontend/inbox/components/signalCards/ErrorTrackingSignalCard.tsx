import { BindLogic, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueListRow } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'
import type { ErrorTrackingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import {
    inboxErrorTrackingIssueLogic,
    InboxErrorTrackingIssueLogicProps,
    InboxErrorTrackingIssueSourceType,
} from './inboxErrorTrackingIssueLogic'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to the error tracking shape (a string `fingerprint`). */
export function isErrorTrackingExtra(value: unknown): value is Record<string, unknown> & ErrorTrackingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.fingerprint === 'string'
}

function asSourceType(sourceType: string): InboxErrorTrackingIssueSourceType {
    return sourceType === 'issue_reopened' || sourceType === 'issue_spiking' ? sourceType : 'issue_created'
}

/** Footer link out to the full error tracking issue scene. */
function ViewIssueLink({ issueId, fingerprint }: { issueId: string; fingerprint: string }): JSX.Element {
    return (
        <Link
            to={urls.errorTrackingIssue(issueId, { fingerprint })}
            target="_blank"
            className="flex items-center gap-1 text-xs font-medium shrink-0"
        >
            View issue <IconExternal className="size-3" />
        </Link>
    )
}

/** Inner body: reads the loaded issue from the bound logic and renders the live row, skeleton, or fallback. */
function ErrorTrackingSignalCardBody({
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
            <div className="flex items-center gap-2 text-xs text-tertiary">
                <span className="font-mono truncate">{fingerprint}</span>
                <span className="flex-1" />
                <ViewIssueLink issueId={linkIssueId} fingerprint={fingerprint} />
            </div>
        )
    }

    if (!mergedIssue || (issueLoading && summaryLoading)) {
        return <LemonSkeleton className="h-16 w-full" />
    }

    return (
        <div className="rounded border bg-surface-primary">
            <ErrorTrackingIssueListRow issue={mergedIssue} canMutateIssues={false} />
        </div>
    )
}

/** Inbox signal card for error tracking issues: embeds the live issue row read-only. */
export function ErrorTrackingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const fingerprint = isErrorTrackingExtra(signal.extra) ? signal.extra.fingerprint : ''
    const sourceType = asSourceType(signal.source_type)

    const logicProps: InboxErrorTrackingIssueLogicProps = {
        issueId: signal.source_id,
        fingerprint,
        sourceType,
    }

    return (
        <SignalCardShell signal={signal}>
            {signal.content && (
                // The signal content ends with the issue's full stack trace in a code fence, which
                // is written for the report LLM rather than for display, so cap it to keep it from
                // swallowing the evidence rail. The View issue link carries the full trace.
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages codeMaxLines={3}>
                    {signal.content}
                </LemonMarkdown>
            )}

            <BindLogic logic={inboxErrorTrackingIssueLogic} props={logicProps}>
                <ErrorTrackingSignalCardBody signal={signal} fingerprint={fingerprint} />
            </BindLogic>

            <div className="flex items-center gap-2 text-xs text-tertiary mt-2">
                <span className="flex-1" />
                <ViewIssueLink issueId={signal.source_id} fingerprint={fingerprint} />
            </div>
        </SignalCardShell>
    )
}

export const errorTrackingSignalCardEntry: SignalCardEntry = {
    key: 'error_tracking',
    matches: (signal) => signal.source_product === 'error_tracking' && isErrorTrackingExtra(signal.extra),
    Component: ErrorTrackingSignalCard,
}

import { combineUrl } from 'kea-router'

import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { ReviewRunApi } from '../../generated/api.schemas'
import { runDuration } from './runDisplay'

// The engine emits its LLM traces under these product tags. They carry no review run id, so a link
// can only narrow to stamphog's traces in the run's own time window, not to this exact run.
const STAMPHOG_AI_PRODUCTS = ['stamphog', 'aio_stamphog']

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <>
            <dt className="text-muted">{label}</dt>
            <dd className="m-0 min-w-0 font-mono text-xs break-all">
                {children ?? <span className="text-muted">—</span>}
            </dd>
        </>
    )
}

function TimeField({ label, time }: { label: string; time?: string | null }): JSX.Element {
    return <Field label={label}>{time ? <TZLabel time={time} /> : null}</Field>
}

function Section({
    title,
    note,
    children,
}: {
    title: string
    note?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="min-w-0">
            <h5 className="text-muted mb-1.5">{title}</h5>
            {/* An auto label column sits against its longest label — a fixed width would open a ragged
                gap beside the short ones. Baseline alignment keeps plain values level with the tag rows. */}
            <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5 text-xs">{children}</dl>
            {note && <p className="text-muted text-xs mt-2 mb-0">{note}</p>}
        </section>
    )
}

function llmTracesUrl(run: ReviewRunApi): string {
    return combineUrl(urls.aiObservabilityTraces(), {
        filters: [
            {
                key: 'ai_product',
                value: STAMPHOG_AI_PRODUCTS,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
        date_from: run.created_at,
        date_to: run.completed_at ?? undefined,
    }).url
}

export function ExpandedRunDetails({ run }: { run: ReviewRunApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 pl-2 pr-4 py-4">
            {run.error && (
                <LemonBanner type="error">
                    <span className="font-mono text-xs">{run.error}</span>
                </LemonBanner>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-x-8 gap-y-6">
                <Section
                    title="Decision"
                    note="The reviewer's reasoning, the individual gates and the sandbox output name changed files, so the API keeps them on the server."
                >
                    <Field label="Engine verdict">{run.gate_result?.final_verdict || null}</Field>
                    <Field label="Gates">
                        {/* The API omits gate_blocked entirely when the run never reached the gates, so an
                            absent value has to read as "didn't get there", not as a pass. */}
                        {run.gate_result?.gate_blocked === undefined ? null : run.gate_result.gate_blocked ? (
                            <LemonTag type="danger">Blocked before review</LemonTag>
                        ) : (
                            <LemonTag type="success">Passed</LemonTag>
                        )}
                    </Field>
                    <Field label="Engine version">{run.output?.stamphog_version || null}</Field>
                    <Field label="Exit code">{run.output?.reviewer_exit_code ?? null}</Field>
                </Section>

                <Section title="Posted to GitHub">
                    <Field label="Review">
                        {run.posted_review_id ? (
                            <Link to={`${run.pr_url}#pullrequestreview-${run.posted_review_id}`} target="_blank">
                                {run.posted_review_id}
                            </Link>
                        ) : null}
                    </Field>
                    <TimeField label="Posted" time={run.verdict_posted_at} />
                    <TimeField label="Approval retracted" time={run.approval_dismissed_at} />
                    <Field label="Branch">{run.head_branch || null}</Field>
                    <Field label="Head commit">{run.head_sha || null}</Field>
                </Section>

                <Section
                    title="Run"
                    note={<Link to={llmTracesUrl(run)}>See stamphog's LLM traces from this window</Link>}
                >
                    <Field label="Run ID">
                        {/* A full UUID doesn't fit the column and wraps to three lines. The prefix is enough
                            to eyeball one row against another, and copy still yields the whole id — which is
                            what it's actually for (grepping worker logs). */}
                        <CopyToClipboardInline description="run ID" explicitValue={run.id}>
                            {run.id.slice(0, 8)}
                        </CopyToClipboardInline>
                    </Field>
                    <Field label="Delivery ID">{run.delivery_id || null}</Field>
                    <TimeField label="Started" time={run.created_at} />
                    <TimeField label="Finished" time={run.completed_at} />
                    <Field label="Took">{runDuration(run)}</Field>
                </Section>
            </div>
        </div>
    )
}

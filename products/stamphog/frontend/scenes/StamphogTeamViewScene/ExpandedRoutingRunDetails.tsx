import { LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import { StamphogRoutingRunApi } from '../../generated/api.schemas'
import { outcomeLabel, ownerDecision, reasonLabel } from './routingRunDisplay'

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <>
            <dt className="text-muted">{label}</dt>
            <dd className="m-0 min-w-0 font-mono text-xs break-all">
                {children ?? <span className="text-muted">-</span>}
            </dd>
        </>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section className="min-w-0">
            <h5 className="text-muted mb-1.5">{title}</h5>
            <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5 text-xs">{children}</dl>
        </section>
    )
}

export function ExpandedRoutingRunDetails({ run, owner }: { run: StamphogRoutingRunApi; owner: string }): JSX.Element {
    const decision = ownerDecision(run, owner)
    const otherOwners = run.owners.filter((entry) => entry.owner !== owner)

    return (
        <div className="grid grid-cols-1 @min-[48rem]/main-content:grid-cols-3 gap-x-8 gap-y-6 pl-2 pr-4 py-4">
            <Section title={`Decision for ${owner}`}>
                <Field label="Reason">{decision ? reasonLabel(decision.reason) : null}</Field>
                <Field label="Model reason">{decision?.model_reason || null}</Field>
                <Field label="Pinned by">
                    {decision && decision.pins.length > 0
                        ? decision.pins.map((pin) => <div key={pin.path}>{pin.path}</div>)
                        : null}
                </Field>
            </Section>

            <Section title="Other owners">
                {otherOwners.length === 0 ? (
                    <dt className="text-muted col-span-2">No other owners</dt>
                ) : (
                    otherOwners.map((entry) => (
                        <Field key={entry.owner} label={entry.owner}>
                            <div className="flex flex-wrap items-center gap-1">
                                <LemonTag type="option">{outcomeLabel(entry.outcome)}</LemonTag>
                                <span>{reasonLabel(entry.reason)}</span>
                            </div>
                        </Field>
                    ))
                )}
            </Section>

            <Section title="Routing run">
                <Field label="Run ID">
                    <CopyToClipboardInline description="run ID" explicitValue={run.id}>
                        {run.id.slice(0, 8)}
                    </CopyToClipboardInline>
                </Field>
                <Field label="Routed">{run.created_at ? <TZLabel time={run.created_at} /> : null}</Field>
                <Field label="Trigger">{run.trigger}</Field>
                <Field label="Scope">{run.scope}</Field>
                <Field label="Model">{run.model || null}</Field>
                <Field label="Head commit">{run.head_sha}</Field>
            </Section>
        </div>
    )
}

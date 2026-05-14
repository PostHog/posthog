import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle, IconClock, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSegmentedButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { DriftDetail } from './detailViews/DriftDetail'
import { DuplicateDetail } from './detailViews/DuplicateDetail'
import { MetadataDetail } from './detailViews/MetadataDetail'
import { NewDefinitionDetail } from './detailViews/NewDefinitionDetail'
import { QuestionDetail } from './detailViews/QuestionDetail'
import { RelationshipDetail } from './detailViews/RelationshipDetail'
import { SchemaSyncDetail } from './detailViews/SchemaSyncDetail'
import { KIND_LABELS, Proposal } from './proposalTypes'
import { semanticLayerProposalsLogic } from './semanticLayerProposalsLogic'

interface ProposalDetailProps {
    proposal: Proposal | null
}

export function ProposalDetail({ proposal }: ProposalDetailProps): JSX.Element {
    const { detailViewMode } = useValues(semanticLayerProposalsLogic)
    const { setDetailViewMode, approveProposal, rejectProposal, snoozeProposal } =
        useActions(semanticLayerProposalsLogic)
    const [rejectMode, setRejectMode] = useState(false)
    const [rejectReason, setRejectReason] = useState('')

    if (!proposal) {
        return (
            <div className="flex flex-col items-center justify-center text-muted-alt p-8 border rounded bg-surface-primary flex-1">
                <span className="text-4xl mb-2" aria-hidden>
                    ✓
                </span>
                <div className="font-medium">All clear</div>
                <div className="text-sm">Nothing waiting in this category.</div>
            </div>
        )
    }

    const isClosed = proposal.status !== 'open'

    return (
        <div className="flex flex-col gap-4 flex-1 min-w-0">
            <header className="flex flex-col gap-2 pb-3 border-b">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonTag type="primary" size="small">
                        {KIND_LABELS[proposal.kind]}
                    </LemonTag>
                    <StatusTag status={proposal.status} />
                    <span className="text-xs text-muted-alt tabular-nums">
                        {Math.round(proposal.confidence * 100)}% confidence
                    </span>
                    <div className="ml-auto">
                        <LemonSegmentedButton
                            size="xsmall"
                            value={detailViewMode}
                            onChange={(v) => setDetailViewMode(v)}
                            options={[
                                { value: 'visual', label: 'Visual' },
                                { value: 'code', label: 'Code' },
                            ]}
                        />
                    </div>
                </div>
                <h2 className="text-lg font-semibold leading-snug">{proposal.title}</h2>
                <p className="text-sm text-muted-alt">{proposal.summary}</p>
            </header>

            {detailViewMode === 'code' ? (
                <CodeView proposal={proposal} />
            ) : (
                <>
                    <ProposalBody proposal={proposal} />
                    <LemonDivider className="my-0" />
                    <WhySection proposal={proposal} />
                    {proposal.impact ? <ImpactSection proposal={proposal} /> : null}
                </>
            )}

            {proposal.status === 'rejected' && proposal.rejectionReason ? (
                <section className="border rounded p-3 bg-danger-highlight text-sm">
                    <div className="text-xs uppercase tracking-wide text-danger mb-1">Rejection reason</div>
                    {proposal.rejectionReason}
                </section>
            ) : null}

            {!isClosed ? (
                <footer className="flex flex-col gap-2 pt-3 border-t mt-auto">
                    {rejectMode ? (
                        <div className="flex flex-col gap-2">
                            <LemonTextArea
                                value={rejectReason}
                                onChange={setRejectReason}
                                placeholder="Why are you rejecting? The agent uses this to improve future proposals."
                                minRows={2}
                                maxRows={4}
                            />
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    type="primary"
                                    status="danger"
                                    disabledReason={rejectReason.trim() === '' ? 'Add a reason' : undefined}
                                    onClick={() => {
                                        rejectProposal(proposal.id, rejectReason.trim())
                                        setRejectReason('')
                                        setRejectMode(false)
                                    }}
                                >
                                    Confirm reject
                                </LemonButton>
                                <LemonButton onClick={() => setRejectMode(false)}>Cancel</LemonButton>
                            </div>
                        </div>
                    ) : (
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="primary"
                                icon={<IconCheckCircle />}
                                onClick={() => approveProposal(proposal.id)}
                            >
                                {proposal.kind === 'metadata' ? 'Approve all' : 'Approve'}
                            </LemonButton>
                            <LemonButton icon={<IconClock />} onClick={() => snoozeProposal(proposal.id)}>
                                Snooze
                            </LemonButton>
                            <LemonButton status="danger" icon={<IconX />} onClick={() => setRejectMode(true)}>
                                Reject
                            </LemonButton>
                            <div className="ml-auto text-xs text-muted-alt">
                                <kbd className="px-1 py-0.5 border rounded text-[10px]">A</kbd> approve ·{' '}
                                <kbd className="px-1 py-0.5 border rounded text-[10px]">X</kbd> reject ·{' '}
                                <kbd className="px-1 py-0.5 border rounded text-[10px]">J</kbd>/
                                <kbd className="px-1 py-0.5 border rounded text-[10px]">K</kbd> navigate
                            </div>
                        </div>
                    )}
                </footer>
            ) : null}
        </div>
    )
}

function StatusTag({ status }: { status: Proposal['status'] }): JSX.Element | null {
    if (status === 'approved') {
        return (
            <LemonTag type="success" size="small">
                Approved
            </LemonTag>
        )
    }
    if (status === 'rejected') {
        return (
            <LemonTag type="danger" size="small">
                Rejected
            </LemonTag>
        )
    }
    if (status === 'snoozed') {
        return (
            <LemonTag type="warning" size="small">
                Snoozed
            </LemonTag>
        )
    }
    return null
}

function ProposalBody({ proposal }: { proposal: Proposal }): JSX.Element {
    switch (proposal.kind) {
        case 'new_definition':
            return <NewDefinitionDetail proposal={proposal} />
        case 'drift':
            return <DriftDetail proposal={proposal} />
        case 'duplicate':
            return <DuplicateDetail proposal={proposal} />
        case 'schema_sync':
            return <SchemaSyncDetail proposal={proposal} />
        case 'relationship':
            return <RelationshipDetail proposal={proposal} />
        case 'metadata':
            return <MetadataDetail proposal={proposal} />
        case 'question':
            return <QuestionDetail proposal={proposal} />
    }
}

function WhySection({ proposal }: { proposal: Proposal }): JSX.Element {
    return (
        <section>
            <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Why</h4>
            <ul className="flex flex-col gap-1.5 text-sm">
                {proposal.provenance.map((p, i) => (
                    <li key={i} className="flex gap-2">
                        <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-fill-highlight-50 shrink-0 self-start">
                            {p.source}
                        </span>
                        {p.detail ? <span className="text-muted-alt">{p.detail}</span> : null}
                    </li>
                ))}
            </ul>
        </section>
    )
}

function ImpactSection({ proposal }: { proposal: Proposal }): JSX.Element | null {
    if (!proposal.impact) {
        return null
    }
    const { insights, dashboards, notebooks, consumers } = proposal.impact
    const stats: string[] = []
    if (insights !== undefined) {stats.push(`${insights} insight${insights === 1 ? '' : 's'}`)}
    if (dashboards !== undefined) {stats.push(`${dashboards} dashboard${dashboards === 1 ? '' : 's'}`)}
    if (notebooks !== undefined) {stats.push(`${notebooks} notebook${notebooks === 1 ? '' : 's'}`)}

    if (stats.length === 0 && !consumers?.length) {
        return null
    }

    return (
        <section>
            <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Impact</h4>
            <div className="text-sm">{stats.join(' · ')}</div>
            {consumers?.length ? (
                <div className="flex flex-wrap gap-1.5 mt-2">
                    {consumers.map((c) => (
                        <LemonTag key={c} size="small">
                            {c}
                        </LemonTag>
                    ))}
                </div>
            ) : null}
        </section>
    )
}

function CodeView({ proposal }: { proposal: Proposal }): JSX.Element {
    const yaml = proposalToYaml(proposal)
    return (
        <section className="flex flex-col gap-2">
            <div className="text-xs text-muted-alt">
                This is what the CLI and MCP tools see. Edits in this view round-trip to the visual form.
            </div>
            <pre className="text-xs bg-bg-3000 border rounded p-3 overflow-x-auto whitespace-pre">{yaml}</pre>
        </section>
    )
}

function proposalToYaml(p: Proposal): string {
    const lines: string[] = []
    lines.push(`kind: ${p.kind}`)
    lines.push(`id: ${p.id}`)
    lines.push(`title: ${JSON.stringify(p.title)}`)
    lines.push(`confidence: ${p.confidence}`)
    lines.push(`status: ${p.status}`)
    if (p.suggestedReviewers?.length) {
        lines.push('suggested_reviewers:')
        for (const r of p.suggestedReviewers) {
            lines.push(`  - ${r}`)
        }
    }
    if (p.kind === 'new_definition') {
        lines.push('definition:')
        lines.push(`  name: ${p.definition.name}`)
        lines.push(`  kind: ${p.definition.kind}`)
        if (p.definition.entity) {lines.push(`  entity: ${p.definition.entity}`)}
        lines.push(`  description: ${JSON.stringify(p.definition.description)}`)
        if (p.definition.suggestedOwner) {lines.push(`  owner: ${p.definition.suggestedOwner}`)}
        if (p.definition.suggestedDimensions?.length) {
            lines.push('  dimensions:')
            for (const d of p.definition.suggestedDimensions) {
                lines.push(`    - ${d}`)
            }
        }
        if (p.definition.formulaSql) {
            lines.push('  sql: |')
            for (const ln of p.definition.formulaSql.split('\n')) {
                lines.push(`    ${ln}`)
            }
        }
    } else if (p.kind === 'drift') {
        lines.push(`target: ${p.targetDefinition}`)
        lines.push(`target_kind: ${p.targetKind}`)
        lines.push(`trigger: ${JSON.stringify(p.triggerEvent)}`)
        lines.push('diff:')
        for (const d of p.diff) {
            lines.push(`  - field: ${d.field}`)
            lines.push(`    before: ${JSON.stringify(d.before)}`)
            lines.push(`    after: ${JSON.stringify(d.after)}`)
        }
    } else if (p.kind === 'duplicate') {
        lines.push(`canonical_index: ${p.recommendedCanonicalIndex}`)
        lines.push('candidates:')
        for (const c of p.candidates) {
            lines.push(`  - id: ${c.id}`)
            lines.push(`    name: ${c.name}`)
            lines.push(`    usage: ${c.usage}`)
        }
    } else if (p.kind === 'schema_sync') {
        lines.push(`source_table: ${p.sourceTable}`)
        lines.push('added_columns:')
        for (const c of p.addedColumns) {
            lines.push(`  - column: ${c.column}`)
            lines.push(`    type: ${c.type}`)
            lines.push(`    role: ${c.suggestedRole}`)
        }
    } else if (p.kind === 'relationship') {
        lines.push(`type: ${p.relationshipType}`)
        lines.push(`left: ${p.leftSide.entity}.${p.leftSide.field}`)
        lines.push(`right: ${p.rightSide.entity}.${p.rightSide.field}`)
    } else if (p.kind === 'metadata') {
        lines.push(`target: ${p.targetDefinition}`)
        lines.push('changes:')
        for (const c of p.changes) {
            lines.push(`  - field: ${JSON.stringify(c.field)}`)
            lines.push(`    after: ${JSON.stringify(c.after)}`)
        }
    } else if (p.kind === 'question') {
        lines.push(`question: ${JSON.stringify(p.question)}`)
        if (p.options) {
            lines.push('options:')
            for (const o of p.options) {
                lines.push(`  - id: ${o.id}`)
                lines.push(`    label: ${o.label}`)
            }
        }
    }
    return lines.join('\n')
}

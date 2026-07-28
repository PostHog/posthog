import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BetStateTag } from './BetStateTag'
import { BetEventRecord, BetNodeRecord, FoundryBetLogicProps, foundryBetLogic } from './foundryBetLogic'

const NODE_STATUS_TAG_TYPE: Record<string, LemonTagType> = {
    spawned: 'default',
    running: 'warning',
    finished: 'success',
    failed: 'danger',
    cancelled: 'muted',
}

function BetNodeTree({ nodes }: { nodes: BetNodeRecord[] }): JSX.Element | null {
    if (nodes.length === 0) {
        return null
    }
    const childrenByParent = new Map<string | null, BetNodeRecord[]>()
    for (const node of nodes) {
        const key = node.parent_id
        childrenByParent.set(key, [...(childrenByParent.get(key) ?? []), node])
    }

    function renderNode(node: BetNodeRecord): JSX.Element {
        const children = childrenByParent.get(node.id) ?? []
        return (
            <li key={node.id}>
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonTag type={NODE_STATUS_TAG_TYPE[node.status] ?? 'default'}>{node.status}</LemonTag>
                    <code className="text-xs">{node.node_id}</code>
                    {node.runner ? <span className="text-muted text-xs">{node.runner}</span> : null}
                    <span className="text-muted text-xs">
                        cost {node.cost_so_far}
                        {node.max_cost != null ? ` / ${node.max_cost}` : ''}
                    </span>
                </div>
                {children.length > 0 && (
                    <ul className="flex flex-col gap-2 pl-4 border-l ml-2 mt-2">{children.map(renderNode)}</ul>
                )}
            </li>
        )
    }

    return (
        <div data-attr="foundry-node-tree">
            <h3 className="mt-4">Node tree</h3>
            <ul className="flex flex-col gap-2">{(childrenByParent.get(null) ?? []).map(renderNode)}</ul>
        </div>
    )
}

interface GateCheckRow {
    name: string
    type: string
    pass: boolean
    required: boolean
    details: string
}

function GateReportCard({ events }: { events: BetEventRecord[] }): JSX.Element | null {
    const latestGateResult = [...events].reverse().find((event) => event.kind === 'gate.result')
    if (!latestGateResult) {
        return null
    }
    const payload = (latestGateResult.payload ?? {}) as Record<string, any>
    const skipped = Boolean(payload.skipped)
    const passed = Boolean(payload.pass)
    const checks = (payload.checks ?? []) as GateCheckRow[]

    return (
        <div className="border rounded p-3 flex flex-col gap-2" data-attr="foundry-gate-card">
            <div className="flex items-center gap-2">
                <strong>Gate</strong>
                {skipped ? (
                    <LemonTag type="muted">skipped</LemonTag>
                ) : passed ? (
                    <LemonTag type="success">pass</LemonTag>
                ) : (
                    <LemonTag type="danger">fail</LemonTag>
                )}
                {payload.review_id ? (
                    <span className="text-muted text-xs">review {String(payload.review_id)}</span>
                ) : null}
            </div>
            {skipped && payload.reason ? <div className="text-muted text-xs">{String(payload.reason)}</div> : null}
            {checks.length > 0 && (
                <LemonTable
                    dataSource={checks}
                    size="small"
                    embedded
                    rowKey={(check) => check.name}
                    expandable={{
                        expandedRowRender: (check) => (
                            <div className="p-2 bg-surface-primary border-t text-xs whitespace-pre-wrap">
                                {check.details}
                            </div>
                        ),
                        rowExpandable: (check) => Boolean(check.details),
                    }}
                    columns={[
                        { title: 'Check', key: 'name', render: (_, check) => <code>{check.name}</code> },
                        { title: 'Type', key: 'type', render: (_, check) => <span>{check.type}</span> },
                        {
                            title: 'Required',
                            key: 'required',
                            render: (_, check) => (
                                <LemonTag type={check.required ? 'default' : 'muted'}>
                                    {check.required ? 'required' : 'optional'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Result',
                            key: 'pass',
                            render: (_, check) =>
                                check.pass ? (
                                    <LemonTag type="success">pass</LemonTag>
                                ) : (
                                    <LemonTag type={check.required ? 'danger' : 'warning'}>fail</LemonTag>
                                ),
                        },
                    ]}
                />
            )}
        </div>
    )
}

function KnowledgeLinks({ events }: { events: BetEventRecord[] }): JSX.Element | null {
    const published = events.filter((event) => event.kind === 'knowledge.published')
    if (published.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-1" data-attr="foundry-knowledge-links">
            <strong>Knowledge published</strong>
            {published.map((event) => {
                const payload = (event.payload ?? {}) as Record<string, any>
                return (
                    <div key={event.id} className="text-xs">
                        <Link to={String(payload.repo ?? '#')}>{String(payload.title || payload.path || 'entry')}</Link>
                        {payload.ref ? <span className="text-muted"> @ {String(payload.ref)}</span> : null}
                    </div>
                )
            })}
        </div>
    )
}

export const scene: SceneExport<FoundryBetLogicProps> = {
    component: FoundryBetScene,
    logic: foundryBetLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
    productKey: ProductKey.FOUNDRY,
}

function EventPayloadSummary({ event }: { event: BetEventRecord }): JSX.Element {
    const payload = (event.payload ?? {}) as Record<string, any>
    if (event.kind === 'state.changed') {
        return (
            <span>
                {String(payload.from)} → {String(payload.to)}
            </span>
        )
    }
    if (event.kind === 'note') {
        return <span className="text-muted">{String(payload.message ?? '')}</span>
    }
    if (event.kind === 'gate.result') {
        const checks = (payload.checks ?? []) as { name?: string }[]
        const violations = (payload.violations ?? []) as { code?: string; message?: string }[]
        return payload.pass ? (
            <span className="flex items-center gap-1">
                <LemonTag type="success">pass</LemonTag>
                {checks.length > 0 ? <span className="text-muted text-xs">{checks.length} checks</span> : null}
            </span>
        ) : (
            <span className="flex flex-wrap gap-1">
                <LemonTag type="danger">fail</LemonTag>
                {violations.map((violation, index) => (
                    <LemonTag key={index} type="warning">
                        {violation.code ?? 'violation'}
                        {violation.message ? `: ${violation.message}` : ''}
                    </LemonTag>
                ))}
            </span>
        )
    }
    const rendered = JSON.stringify(payload)
    return <code className="text-xs">{rendered === '{}' ? '' : rendered}</code>
}

export function FoundryBetScene(): JSX.Element {
    const { bet, betLoading, events, eventsLoading, nodes } = useValues(foundryBetLogic)
    const { fund, recordVerdict } = useActions(foundryBetLogic)

    if (!bet) {
        return <SceneContent>{betLoading ? <></> : <>Bet not found</>}</SceneContent>
    }

    const isDrafted = bet.state === 'drafted'
    const isExposed = bet.state === 'exposed'

    return (
        <SceneContent>
            <SceneTitleSection
                name={bet.slug}
                description={bet.hypothesis}
                resourceType={{ type: 'experiment' }}
                actions={
                    <div className="flex gap-2">
                        {isDrafted && (
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={betLoading}
                                onClick={fund}
                                data-attr="foundry-bet-fund"
                            >
                                Fund bet
                            </LemonButton>
                        )}
                        {isExposed && (
                            <>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    loading={betLoading}
                                    onClick={() => recordVerdict('promoted')}
                                    data-attr="foundry-bet-promote"
                                >
                                    Promote
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    size="small"
                                    loading={betLoading}
                                    onClick={() => recordVerdict('rolled_back')}
                                    data-attr="foundry-bet-rollback"
                                >
                                    Roll back
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    loading={betLoading}
                                    onClick={() => recordVerdict('iterate')}
                                    data-attr="foundry-bet-iterate"
                                >
                                    Iterate
                                </LemonButton>
                            </>
                        )}
                    </div>
                }
            />
            <div className="flex flex-wrap items-center gap-2" data-attr="foundry-bet-meta">
                <BetStateTag bet={bet} />
                <LemonTag type={bet.execution_mode === 'managed' ? 'completion' : 'default'}>
                    {bet.execution_mode}
                </LemonTag>
                <LemonTag>iteration {bet.iteration}</LemonTag>
                {bet.success_metric?.name ? (
                    <LemonTag type="highlight">
                        metric: {String(bet.success_metric.name)}
                        {bet.success_metric.target ? ` (${String(bet.success_metric.target)})` : ''}
                    </LemonTag>
                ) : null}
                {(bet.guardrails ?? []).map((guardrail, index) => (
                    <LemonTag key={index} type="caution">
                        guardrail: {String(guardrail.name)}
                    </LemonTag>
                ))}
                {bet.budget?.usd ? <LemonTag>budget: ${String(bet.budget.usd)}</LemonTag> : null}
                {bet.feature_flag_id ? (
                    <Link to={urls.featureFlag(bet.feature_flag_id)} data-attr="foundry-bet-flag-link">
                        Flag: {bet.feature_flag_key}
                    </Link>
                ) : null}
                {bet.experiment_id ? (
                    <Link to={urls.experiment(bet.experiment_id)} data-attr="foundry-bet-experiment-link">
                        Experiment
                    </Link>
                ) : null}
            </div>
            {(bet.sources ?? []).length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {(bet.sources ?? []).map((source, index) =>
                        source.url ? (
                            <Link key={index} to={String(source.url)}>
                                {String(source.label ?? source.url)}
                            </Link>
                        ) : (
                            <LemonTag key={index}>{String(source.label)}</LemonTag>
                        )
                    )}
                </div>
            )}
            <GateReportCard events={events} />
            <KnowledgeLinks events={events} />
            <BetNodeTree nodes={nodes} />
            <h3 className="mt-4">Timeline</h3>
            <LemonTable
                loading={eventsLoading}
                dataSource={events}
                emptyState="No events yet. Orchestrators report progress here."
                columns={[
                    {
                        title: 'When',
                        key: 'created_at',
                        width: 180,
                        render: (_, event: BetEventRecord) => <TZLabel time={event.created_at} />,
                    },
                    {
                        title: 'Event',
                        key: 'kind',
                        width: 180,
                        render: (_, event: BetEventRecord) => <LemonTag type="option">{event.kind}</LemonTag>,
                    },
                    {
                        title: 'Detail',
                        key: 'payload',
                        render: (_, event: BetEventRecord) => <EventPayloadSummary event={event} />,
                    },
                ]}
            />
        </SceneContent>
    )
}

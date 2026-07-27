import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BetStateTag } from './BetStateTag'
import { BetEventRecord, FoundryBetLogicProps, foundryBetLogic } from './foundryBetLogic'

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
    if (event.kind === 'gate.result') {
        const violations = (payload.violations ?? []) as { code?: string; message?: string }[]
        return payload.pass ? (
            <LemonTag type="success">pass</LemonTag>
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
    const { bet, betLoading, events, eventsLoading } = useValues(foundryBetLogic)
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

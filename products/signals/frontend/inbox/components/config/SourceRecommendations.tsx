import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { isExternalSignalSource } from '../../externalSignalSources'
import { WarehouseBackedSource, signalSourcesLogic } from '../../signalSourcesLogic'
import { SourceRecommendation } from '../../sourceRecommendations'
import { SourceAgentIcon } from './SourceAgentIcon'

function recommendationDescription({ agent, reason, description }: SourceRecommendation): string {
    switch (reason) {
        case 'synced':
            return 'Already syncing to your warehouse, so watching turns on with one click.'
        case 'integration':
            return 'Already connected to PostHog. Agents can start reading it right away.'
        case 'default':
            return description ?? agent.watches
    }
}

export function SourceRecommendations(): JSX.Element | null {
    const { visibleSourceRecommendations, externalSourceStates, isCiSignalsToggling } = useValues(signalSourcesLogic)
    const { selectCatalogSource } = useActions(signalSourcesLogic)

    if (visibleSourceRecommendations.length === 0) {
        return null
    }

    return (
        <div
            className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2"
            data-attr="signal-source-recommendations"
        >
            {/* auto-fill keeps the empty tracks, so one or two cards stay card-sized rather than stretching across the row. */}
            {visibleSourceRecommendations.map((recommendation) => {
                const { agent, reason } = recommendation
                const source = agent.source as WarehouseBackedSource
                const state = isExternalSignalSource(source) ? externalSourceStates[source] : null
                const loading = state ? state.loading : isCiSignalsToggling
                return (
                    <div
                        key={agent.source}
                        className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-3"
                        data-attr="signal-source-recommendation"
                        data-source={agent.source}
                    >
                        <div className="flex items-center gap-2">
                            <SourceAgentIcon agent={agent} />
                            <span className="truncate text-sm font-medium">{agent.label}</span>
                            {agent.alpha && (
                                <LemonTag type="completion" size="small">
                                    Alpha
                                </LemonTag>
                            )}
                        </div>
                        <p className="mb-0 flex-1 text-xs leading-4 text-secondary">
                            {recommendationDescription(recommendation)}
                        </p>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            className="self-start"
                            loading={loading}
                            disabledReason={state?.blockedReason}
                            onClick={() => selectCatalogSource(source, 'recommendation')}
                            data-attr="signal-source-recommendation-action"
                        >
                            {reason === 'synced' ? 'Turn on' : 'Connect'}
                        </LemonButton>
                    </div>
                )
            })}
        </div>
    )
}

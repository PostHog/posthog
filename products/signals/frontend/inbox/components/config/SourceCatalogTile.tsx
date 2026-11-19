import { useActions } from 'kea'

import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { SourceCatalogItem, WarehouseBackedSource, signalSourcesLogic } from '../../signalSourcesLogic'
import { SourceAgentIcon } from './SourceAgentIcon'

export function SourceCatalogTile({ item }: { item: SourceCatalogItem }): JSX.Element {
    const { selectCatalogSource } = useActions(signalSourcesLogic)

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-3 p-3"
            data-attr={item.recommendation ? 'signal-source-recommendation' : 'signal-source-catalog-tile'}
            data-source={item.agent.source}
        >
            <div className="flex items-start gap-2">
                <SourceAgentIcon agent={item.agent} size="medium" />
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="text-sm font-semibold">{item.agent.label}</span>
                    {item.agent.alpha && (
                        <LemonTag type="completion" size="small">
                            Alpha
                        </LemonTag>
                    )}
                </div>
            </div>
            <p className="mb-0 flex-1 text-xs text-secondary">
                {item.recommendation?.reason === 'integration'
                    ? 'Already connected to PostHog. Agents can start reading it right away.'
                    : (item.recommendation?.description ?? item.agent.watches)}
            </p>
            <LemonButton
                type="secondary"
                size="small"
                className="self-start"
                loading={item.loading}
                disabledReason={item.blockedReason}
                onClick={() =>
                    selectCatalogSource(
                        item.agent.source as WarehouseBackedSource,
                        item.recommendation ? 'recommendation' : 'catalog'
                    )
                }
                aria-label={`Connect ${item.agent.label}`}
                data-attr={item.recommendation ? 'signal-source-recommendation-action' : 'signal-source-catalog-tile'}
                data-source={item.agent.source}
            >
                Connect
            </LemonButton>
        </LemonCard>
    )
}

import { useValues } from 'kea'

import { IconArrowRight, IconMegaphone, IconX } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import {
    MarketingAnalyticsCrossSellLogicProps,
    marketingAnalyticsCrossSellLogic,
} from './marketingAnalyticsCrossSellLogic'
import { captureMarketingCrossSellClick } from './marketingCrossSellAttribution'

export function MarketingAnalyticsCrossSellCard(
    props: MarketingAnalyticsCrossSellLogicProps & { onDismiss: () => void }
): JSX.Element | null {
    const { hasPaidTraffic, hasConnectedSources, hasConnectedSourcesLoading, destination } = useValues(
        marketingAnalyticsCrossSellLogic(props)
    )
    if (!hasPaidTraffic || hasConnectedSources === null || hasConnectedSourcesLoading) {
        return null
    }
    const description = hasConnectedSources
        ? 'Compare campaign spend with website conversions in Marketing analytics.'
        : 'Connect your ad sources in Marketing analytics to compare campaign spend with website conversions.'

    return (
        <div className="border-t p-4 bg-surface-primary rounded-b" data-attr="web-analytics-marketing-cross-sell">
            <LemonCard hoverEffect={false} className="p-4">
                <LemonButton
                    className="absolute top-2 right-2"
                    type="tertiary"
                    size="xsmall"
                    icon={<IconX />}
                    aria-label="Dismiss Marketing analytics suggestion"
                    data-attr="web-analytics-marketing-cross-sell-dismiss"
                    onClick={props.onDismiss}
                />
                <div className="flex items-center gap-2 font-semibold pr-6 mb-2">
                    <IconMegaphone className="shrink-0" />
                    <span>Analyze your paid traffic</span>
                </div>
                <p className="text-secondary mb-3">{description}</p>
                <div className="flex">
                    <LemonButton
                        type="secondary"
                        size="small"
                        sideIcon={<IconArrowRight />}
                        to={destination}
                        data-attr="web-analytics-marketing-cross-sell-open"
                        onClick={() =>
                            captureMarketingCrossSellClick(props.teamId, props.breakdown, hasConnectedSources)
                        }
                    >
                        {hasConnectedSources ? 'Analyze in Marketing analytics' : 'Connect ad sources'}
                    </LemonButton>
                </div>
            </LemonCard>
        </div>
    )
}

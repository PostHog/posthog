import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconArrowRight, IconMegaphone, IconX } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import {
    MarketingAnalyticsCrossSellLogicProps,
    marketingAnalyticsCrossSellLogic,
} from './marketingAnalyticsCrossSellLogic'

export function MarketingAnalyticsCrossSellCard(
    props: MarketingAnalyticsCrossSellLogicProps & { onDismiss: () => void }
): JSX.Element | null {
    const { hasPaidTraffic, hasConnectedSources, hasConnectedSourcesLoading, destination } = useValues(
        marketingAnalyticsCrossSellLogic(props)
    )
    if (!hasPaidTraffic || hasConnectedSources === null || hasConnectedSourcesLoading) {
        return null
    }
    const title =
        props.breakdown === WebStatsBreakdown.InitialUTMSource
            ? 'See ad spend alongside your traffic'
            : props.breakdown === WebStatsBreakdown.InitialUTMCampaign
              ? 'See which campaigns convert'
              : 'Analyze your paid traffic'
    const description =
        props.breakdown === WebStatsBreakdown.InitialUTMSource
            ? hasConnectedSources
                ? 'Compare traffic, spend and conversions across your connected ad sources in Marketing analytics.'
                : 'Connect ad sources in Marketing analytics to compare traffic, spend and conversions by source.'
            : hasConnectedSources
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
                    <span>{title}</span>
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
                            posthog.capture('web analytics marketing cross sell clicked', {
                                breakdown: props.breakdown,
                                has_connected_sources: hasConnectedSources,
                            })
                        }
                    >
                        {hasConnectedSources ? 'Analyze in Marketing analytics' : 'Connect ad sources'}
                    </LemonButton>
                </div>
            </LemonCard>
        </div>
    )
}

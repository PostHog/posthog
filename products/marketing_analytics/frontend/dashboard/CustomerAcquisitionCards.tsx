import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { SamplingRate } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { WebOverviewItem } from '~/queries/schema/schema-general'

import { customerAcquisitionMetrics } from './customerAcquisitionMetrics'
import { MarketingQueryError } from './MarketingQueryError'

interface CustomerAcquisitionCardsProps {
    configurationLoading: boolean
    configured: boolean
    loading: boolean
    error: boolean
    queryId?: string | null
    customerResults?: WebOverviewItem[]
    trafficResults?: WebOverviewItem[]
    samplingRate?: SamplingRate
    onConfigure: () => void
    onRetry: () => void
}

export function CustomerAcquisitionCards({
    configurationLoading,
    configured,
    loading,
    error,
    queryId,
    customerResults,
    trafficResults,
    samplingRate,
    onConfigure,
    onRetry,
}: CustomerAcquisitionCardsProps): JSX.Element {
    return (
        <div className="contents">
            {configurationLoading ? (
                <>
                    <LemonSkeleton className="h-36" />
                    <LemonSkeleton className="h-36" />
                </>
            ) : !configured ? (
                <LemonCard hoverEffect={false} className="h-full !p-3 flex flex-col justify-between gap-2">
                    <span className="font-semibold">New customers</span>
                    <span className="text-secondary">Mark an event or action goal as a new customer goal.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={onConfigure}
                        data-attr="marketing-configure-customer-goal"
                    >
                        Configure in Setup
                    </LemonButton>
                </LemonCard>
            ) : error ? (
                <MarketingQueryError
                    message="Could not load new customers."
                    queryId={queryId}
                    onRetry={onRetry}
                    loading={loading}
                />
            ) : (
                <OverviewMetricCardGrid
                    layout="contents"
                    items={customerAcquisitionMetrics(customerResults, trafficResults).map((item) => ({
                        ...item,
                        value: item.value,
                    }))}
                    loading={loading}
                    numSkeletons={2}
                    samplingRate={samplingRate}
                    labelFromKey={(key) =>
                        key === 'unique conversions' ? (
                            'New customers'
                        ) : (
                            <span className="inline-flex items-center gap-1">
                                Customer-to-visitor ratio
                                <Tooltip title="Unique people completing the selected customer goal divided by visitors with a pageview or screenview, multiplied by 100. Each row uses its own channel or campaign. This can exceed 100% when goals complete without pageviews or screenviews.">
                                    <IconInfo
                                        className="shrink-0 text-secondary"
                                        aria-label="How customer-to-visitor ratio is calculated"
                                    />
                                </Tooltip>
                            </span>
                        )
                    }
                />
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { UsageBucket, usageOverviewLogic } from '../../logics/usageOverviewLogic'
import { SignalSourceProduct } from '../../types'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { RecordedSpend } from './RecordedSpend'

export function UsageOverview(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = usageOverviewLogic({ teamId: currentTeamId ?? 0 })
    const { buckets, loading, failed } = useValues(logic)
    const { loadUsage } = useActions(logic)

    if (failed) {
        return (
            <LemonBanner type="error" action={<LemonButton onClick={loadUsage}>Retry</LemonButton>}>
                Couldn't load usage.
            </LemonBanner>
        )
    }
    if (loading) {
        return <LemonSkeleton className="h-32 w-full" />
    }
    return (
        <div data-attr="usage-overview">
            <LemonTable<UsageBucket>
                dataSource={buckets}
                rowKey="sourceProduct"
                size="small"
                columns={[
                    {
                        title: 'Source',
                        key: 'source',
                        render: (_, { sourceProduct }) =>
                            sourceProduct === SignalSourceProduct.SignalsScout
                                ? 'Scouts'
                                : (getSourceProductMeta(sourceProduct)?.label ?? sourceProduct),
                    },
                    {
                        title: 'Usage',
                        key: 'usage',
                        align: 'right',
                        render: (_, { sourceProduct, amount }) => (
                            <RecordedSpend
                                amount={amount}
                                description={
                                    sourceProduct === SignalSourceProduct.SignalsScout
                                        ? 'Usage for scout runs started and scout signals received in the last 30 days, including later research.'
                                        : 'Accumulated processing usage for signals received in the last 30 days, including later research.'
                                }
                            />
                        ),
                    },
                ]}
            />
        </div>
    )
}

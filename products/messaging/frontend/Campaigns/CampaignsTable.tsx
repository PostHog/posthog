import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonDialog, LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { campaignsLogic } from './campaignsLogic'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'
import { HogFlow } from './hogflows/types'

function CampaignActionsSummary({ campaign }: { campaign: HogFlow }): JSX.Element {
    const actionsByType = useMemo(() => {
        return campaign.actions.reduce(
            (acc, action) => {
                const step = getHogFlowStep(action, {})
                if (!step || !step.type.startsWith('function')) {
                    return acc
                }
                const key = 'template_id' in action.config ? action.config.template_id : action.type
                acc[key] = {
                    count: (acc[key]?.count || 0) + 1,
                    icon: step.icon,
                    color: step.color,
                }
                return acc
            },
            {} as Record<
                string,
                {
                    count: number
                    icon: JSX.Element
                    color: string
                }
            >
        )
    }, [campaign.actions])

    return (
        <Link to={urls.messagingCampaign(campaign.id, 'workflow')}>
            <div className="flex flex-row gap-2 items-center">
                {Object.entries(actionsByType).map(([type, { count, icon, color }]) => (
                    <div
                        key={type}
                        className="rounded px-1 flex items-center justify-center gap-1"
                        style={{
                            backgroundColor: `${color}20`,
                            color,
                        }}
                    >
                        {icon} {count}
                    </div>
                ))}
            </div>
        </Link>
    )
}

export function CampaignsTable(): JSX.Element {
    useMountedLogic(campaignsLogic)
    const { campaigns, campaignsLoading } = useValues(campaignsLogic)
    const { toggleCampaignStatus, duplicateCampaign, deleteCampaign } = useActions(campaignsLogic)

    const columns: LemonTableColumns<HogFlow> = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: (_, item) => {
                return (
                    <LemonTableLink
                        to={urls.messagingCampaign(item.id)}
                        title={item.name}
                        description={item.description}
                    />
                )
            },
        },

        {
            title: 'Trigger',
            width: 0,
            render: (_, item) => {
                return (
                    <Link to={urls.messagingCampaign(item.id, 'workflow') + '?node=trigger_node'}>
                        <LemonTag type="default">{capitalizeFirstLetter(item.trigger?.type ?? 'unknown')}</LemonTag>
                    </Link>
                )
            },
        },
        {
            title: 'Dispatches',
            width: 0,
            render: (_, item) => {
                return <CampaignActionsSummary campaign={item} />
            },
        },
        {
            ...(updatedAtColumn() as LemonTableColumn<HogFlow, any>),
            width: 0,
        },
        {
            title: 'Last 7 days',
            width: 0,
            render: (_, { id }) => {
                return (
                    <Link to={urls.messagingCampaign(id, 'metrics')}>
                        <AppMetricsSparkline
                            logicKey={id}
                            forceParams={{
                                appSource: 'hog_flow',
                                appSourceId: id,
                                metricKind: ['success', 'failure'],
                                breakdownBy: 'metric_kind',
                                interval: 'day',
                                dateFrom: '-7d',
                            }}
                        />
                    </Link>
                )
            },
        },

        {
            title: 'Status',
            width: 0,
            key: 'status',
            sorter: (a, b) => a.status.localeCompare(b.status),
            render: (_, item) => {
                return (
                    <LemonTag type={item.status === 'active' ? 'success' : 'default'}>
                        {capitalizeFirstLetter(item.status)}
                    </LemonTag>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, campaign: HogFlow) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    data-attr="campaign-edit"
                                    fullWidth
                                    status={campaign.status === 'draft' ? 'default' : 'danger'}
                                    onClick={() => toggleCampaignStatus(campaign)}
                                    tooltip={
                                        campaign.status === 'draft'
                                            ? 'Enables the campaign to start sending messages'
                                            : 'Disables the campaign from sending any new messages. In-progress workflows will end immediately.'
                                    }
                                >
                                    {campaign.status === 'draft' ? 'Enable' : 'Disable'}
                                </LemonButton>
                                <LemonButton
                                    data-attr="campaign-duplicate"
                                    fullWidth
                                    onClick={() => duplicateCampaign(campaign)}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    data-attr="campaign-delete"
                                    fullWidth
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete campaign',
                                            description: (
                                                <p>
                                                    Are you sure you want to delete the campaign "
                                                    <strong>{campaign.name}</strong>"? This action cannot be undone.
                                                    In-progress workflows will end immediately.
                                                </p>
                                            ),
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => {
                                                    deleteCampaign(campaign)
                                                },
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="campaigns-section">
            <LemonTable
                dataSource={campaigns}
                loading={campaignsLoading}
                columns={columns}
                defaultSorting={{ columnKey: 'status', order: 1 }}
            />
        </div>
    )
}

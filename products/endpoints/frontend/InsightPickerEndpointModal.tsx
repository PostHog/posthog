import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'

import { IconCode2, IconFunnels, IconPlus, IconRetention, IconTrends } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightsTable } from 'scenes/saved-insights/SavedInsightsTable'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { InsightType, QueryBasedInsightModel } from '~/types'

import { EndpointFromInsightModal } from './EndpointFromInsightModal'
import { endpointLogic } from './endpointLogic'
import { insightPickerEndpointModalLogic } from './insightPickerEndpointModalLogic'

const QUICK_CREATE_TYPES = [
    { type: InsightType.TRENDS, icon: IconTrends, label: 'Trend' },
    { type: InsightType.FUNNELS, icon: IconFunnels, label: 'Funnel' },
    { type: InsightType.RETENTION, icon: IconRetention, label: 'Retention' },
]

interface InsightPickerEndpointModalProps {
    tabId: string
}

export function InsightPickerEndpointModal({ tabId }: InsightPickerEndpointModalProps): JSX.Element {
    const { isOpen, selectedInsight, showMoreInsightTypes } = useValues(insightPickerEndpointModalLogic)
    const { closeModal, selectInsight, toggleShowMoreInsightTypes } = useActions(insightPickerEndpointModalLogic)
    const { openCreateFromInsightModal } = useActions(endpointLogic({ tabId }))

    const insightQuery: HogQLQuery | InsightQueryNode | null = selectedInsight?.query
        ? isNodeWithSource(selectedInsight.query)
            ? (selectedInsight.query.source as HogQLQuery | InsightQueryNode)
            : (selectedInsight.query as HogQLQuery | InsightQueryNode)
        : null

    const additionalTypes = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([type, meta]) =>
            meta.inMenu &&
            type !== InsightType.JSON &&
            type !== InsightType.HOG &&
            !QUICK_CREATE_TYPES.some((qt) => qt.type === type)
    )

    return (
        <>
            <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
                <LemonModal
                    title="New insight-based endpoint"
                    onClose={closeModal}
                    isOpen={isOpen}
                    width="min(80vw, 64rem)"
                >
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-3 p-4 bg-surface-secondary rounded-lg">
                            <IconPlus className="text-2xl text-secondary shrink-0" />
                            <div className="flex-1 min-w-[200px]">
                                <div className="font-semibold text-base">Create an endpoint from a new insight</div>
                                <div className="text-sm text-secondary">
                                    <>
                                        Once the insight is saved, open the right side panel and click
                                        <br /> <IconCode2 /> <code>Create endpoint</code>.
                                    </>
                                </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                {QUICK_CREATE_TYPES.map(({ type, icon: Icon, label }) => (
                                    <LemonButton
                                        key={type}
                                        type="primary"
                                        icon={<Icon />}
                                        to={urls.insightNew({ type })}
                                        tooltip={INSIGHT_TYPES_METADATA[type]?.description}
                                        data-attr={`endpoint-quick-create-${type.toLowerCase()}`}
                                    >
                                        {label}
                                    </LemonButton>
                                ))}
                                <Popover
                                    visible={showMoreInsightTypes}
                                    onClickOutside={() => toggleShowMoreInsightTypes()}
                                    overlay={
                                        <div className="p-2 space-y-1 min-w-48">
                                            {additionalTypes.map(([type, metadata]) => {
                                                const Icon = metadata.icon
                                                return (
                                                    <LemonButton
                                                        key={type}
                                                        type="tertiary"
                                                        fullWidth
                                                        icon={Icon ? <Icon /> : undefined}
                                                        to={urls.insightNew({ type: type as InsightType })}
                                                        data-attr={`endpoint-create-${type.toLowerCase()}`}
                                                    >
                                                        {metadata.name}
                                                    </LemonButton>
                                                )
                                            })}
                                        </div>
                                    }
                                >
                                    <LemonButton type="secondary" onClick={() => toggleShowMoreInsightTypes()}>
                                        More
                                    </LemonButton>
                                </Popover>
                            </div>
                        </div>

                        <div>
                            <div className="font-semibold text-base mb-2">
                                Create an endpoint from an existing insight
                            </div>
                            <SavedInsightsTable
                                onToggle={(insight: QueryBasedInsightModel) => {
                                    selectInsight(insight)
                                    openCreateFromInsightModal()
                                }}
                            />
                        </div>
                    </div>
                </LemonModal>
            </BindLogic>

            {insightQuery && (
                <EndpointFromInsightModal
                    tabId={tabId}
                    insightQuery={insightQuery}
                    insightShortId={selectedInsight?.short_id}
                />
            )}
        </>
    )
}

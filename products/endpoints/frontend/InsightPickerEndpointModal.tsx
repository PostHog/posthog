import { useActions, useValues } from 'kea'

import { IconFunnels, IconPlus, IconRetention, IconTrends } from '@posthog/icons'
import { IconCode2 } from '@posthog/icons'

import { InsightPickerTable } from 'lib/components/InsightPicker/InsightPickerTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { urls } from 'scenes/urls'

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

interface InsightEndpointModalProps {
    tabId: string
}

export function InsightPickerEndpointModal({ tabId }: InsightEndpointModalProps): JSX.Element {
    const { isOpen, selectedInsight, showMoreInsightTypes } = useValues(insightPickerEndpointModalLogic)
    const { closeModal, selectInsight, clearSelectedInsight, toggleShowMoreInsightTypes } = useActions(
        insightPickerEndpointModalLogic
    )
    const { setEndpointName, setEndpointDescription, setIsUpdateMode, setSelectedEndpointName } = useActions(
        endpointLogic({ tabId })
    )

    const insightQuery = selectedInsight?.query
        ? isNodeWithSource(selectedInsight.query)
            ? selectedInsight.query.source
            : selectedInsight.query
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
            <LemonModal
                title="New insight-based endpoint"
                onClose={closeModal}
                isOpen={isOpen}
                width="min(80vw, 64rem)"
            >
                <div className="space-y-4">
                    <div className="flex items-center gap-3 p-4 bg-surface-secondary rounded-lg">
                        <IconPlus className="text-2xl text-secondary shrink-0" />
                        <div className="flex-1">
                            <div className="font-semibold text-base">From a new insight</div>
                            <div className="text-sm text-secondary">
                                Build a new insight and create an endpoint from it
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
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

                    <InsightPickerTable
                        logicKey="endpoints"
                        renderActionColumn={(insight: QueryBasedInsightModel) => (
                            <LemonButton
                                type="primary"
                                size="small"
                                className="whitespace-nowrap"
                                onClick={() => selectInsight(insight)}
                                data-attr="use-insight-for-endpoint"
                                tooltip="Create endpoint from this insight"
                            >
                                <IconCode2 />
                            </LemonButton>
                        )}
                    />
                </div>
            </LemonModal>

            {insightQuery && (
                <EndpointFromInsightModal
                    isOpen={!!selectedInsight}
                    closeModal={() => {
                        setEndpointName('')
                        setEndpointDescription('')
                        setIsUpdateMode(false)
                        setSelectedEndpointName(null)
                        clearSelectedInsight()
                    }}
                    tabId={tabId}
                    insightQuery={insightQuery}
                    insightShortId={selectedInsight?.short_id}
                />
            )}
        </>
    )
}

import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { InsightSubscribeProminentButton } from 'lib/components/Scenes/InsightSubscribeProminentButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { getOverrideWarningPropsForButton } from 'scenes/insights/utils'

import { isBIVisualizationNode } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, InsightLogicProps, ItemMode } from '~/types'

import { insightModalsLogic } from 'products/product_analytics/frontend/insights/insightScene/insightModalsLogic'

import { openInsightEditor } from './openInsightEditor'
import { QuillInsightSaveButton } from './QuillInsightSaveButton'

export function QuillInsightPageHeaderActions({
    insightLogicProps,
    isPersistedInsight,
    canCreateAlertForInsight,
    saveInsightToFolder,
}: {
    insightLogicProps: InsightLogicProps
    isPersistedInsight: boolean
    canCreateAlertForInsight: boolean
    saveInsightToFolder: (redirectToViewMode?: boolean) => void
}): JSX.Element {
    const { insightMode, filtersOverride, variablesOverride, dashboardId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)
    const {
        insightProps,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        hasDashboardItemId: isSavedInsight,
    } = useValues(insightLogic(insightLogicProps))
    const { saveAs } = useActions(insightLogic(insightLogicProps))
    const { openAddToDashboardModal, saveAndAddToDashboard } = useActions(insightModalsLogic(insightLogicProps))
    const { query, queryChanged } = useValues(insightDataLogic(insightProps))
    const { cancelChanges } = useActions(insightDataLogic(insightProps))
    const biEnabled = useFeatureFlag('SQL_EDITOR_BI_MODE')

    const overrideWarning = getOverrideWarningPropsForButton(query, filtersOverride, variablesOverride)

    const onEdit = (): void =>
        openInsightEditor({
            query,
            insightShortId: insight.short_id,
            dashboardId,
            queryChanged,
            enterEditMode: () => setInsightMode(ItemMode.Edit, null),
        })

    return (
        <>
            {insightMode === ItemMode.Edit && isSavedInsight && (
                <Button
                    variant="outline"
                    onClick={() => {
                        cancelChanges()
                        setInsightMode(ItemMode.View, null)
                    }}
                    data-attr="insight-cancel-edit-button"
                >
                    Cancel
                </Button>
            )}

            {insightMode !== ItemMode.Edit && isPersistedInsight && (
                <Button
                    variant="outline"
                    data-attr="insight-add-to-dashboard-prominent-button"
                    onClick={() => openAddToDashboardModal()}
                >
                    <IconPlus />
                    Add to dashboard
                </Button>
            )}

            {insightMode !== ItemMode.Edit && isPersistedInsight && (
                <InsightSubscribeProminentButton
                    insightShortId={insight.short_id!}
                    canCreateAlert={canCreateAlertForInsight}
                />
            )}

            {insightMode !== ItemMode.Edit ? (
                canEditInsight && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Insight}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={insight.user_access_level}
                    >
                        <Button
                            variant="primary"
                            onClick={onEdit}
                            tooltip={
                                typeof overrideWarning.tooltip === 'function'
                                    ? overrideWarning.tooltip()
                                    : overrideWarning.tooltip
                            }
                            disabledReason={
                                isBIVisualizationNode(query) && !biEnabled
                                    ? 'Business intelligence is not enabled for this project'
                                    : undefined
                            }
                            data-attr="insight-edit-button"
                        >
                            {overrideWarning.icon}
                            Edit
                        </Button>
                    </AccessControlAction>
                )
            ) : (
                <QuillInsightSaveButton
                    saveAs={() => saveAs(undefined, undefined, 'Unfiled/Insights')}
                    saveInsight={saveInsightToFolder}
                    isSaved={isSavedInsight}
                    addingToDashboard={!insight.id && !!insight.dashboards?.length}
                    insightSaving={insightSaving}
                    insightChanged={insightChanged || queryChanged}
                    onSaveAndAddToDashboard={isPersistedInsight ? () => saveAndAddToDashboard() : undefined}
                />
            )}
        </>
    )
}

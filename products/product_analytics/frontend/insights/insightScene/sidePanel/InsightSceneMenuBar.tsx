import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconBell,
    IconCode2,
    IconCopy,
    IconDownload,
    IconEndpoints,
    IconGraph,
    IconImage,
    IconPencil,
    IconPeople,
    IconPlusSmall,
    IconPulse,
    IconShare,
    IconTrash,
    IconWarning,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { captureImageLogic } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { AnalyticsCollectionDialogHost } from 'scenes/analytics/AnalyticsCollectionDialogHost'
import { ShareToSpaceTarget } from 'scenes/analytics/analyticsShareLogic'
import { useAnalyticsCollectionActions } from 'scenes/analytics/useAnalyticsCollectionActions'
import { useScenePinAction } from 'scenes/analytics/useScenePinAction'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { getOverrideWarningPropsForButton, unsavedSqlInsightQuery } from 'scenes/insights/utils'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { useAddToNotebookAction } from 'scenes/notebooks/useAddToNotebookAction'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { INSIGHT_GRAPH_SELECTOR, INSIGHT_SCREENSHOT_KEY } from '~/queries/nodes/InsightViz/insightImageCapture'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery, isInsightVizNode } from '~/queries/schema/node-guards'
import { NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    ExporterFormat,
    InsightLogicProps,
    InsightModel,
    ItemMode,
    SidePanelTab,
} from '~/types'

import { areAlertsSupportedForInsight } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { metricsLogic } from 'products/data_catalog/frontend/metricsLogic'
import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { insightModalsLogic } from '../insightModalsLogic'
import { openInsightEditor } from '../openInsightEditor'
import { QuillInsightMonitorButton } from '../QuillInsightMonitorButton'
import { QuillInsightSaveButton } from '../QuillInsightSaveButton'
import { openSaveAsCohortDialog } from './insightSidePanelDialogs'

const RESOURCE_TYPE = 'insight'

export function InsightSceneMenuBar({
    insightLogicProps,
}: {
    insightLogicProps: InsightLogicProps
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }

    return <InsightSceneMenuBarInner insightLogicProps={insightLogicProps} />
}

function InsightSceneMenuBarInner({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const {
        insightProps,
        insight,
        hasDashboardItemId,
        canEditInsight,
        isSavingTags,
        insightDuplicating,
        insightChanged,
        insightSaving,
    } = useValues(theInsightLogic)
    const { duplicateInsight, deleteInsight, setInsightMetadata, saveInsight, saveAs } = useActions(theInsightLogic)

    const theInsightDataLogic = insightDataLogic(insightProps)
    const {
        query,
        queryChanged,
        hogQL,
        exportContext,
        hogQLVariables,
        canEditInSqlEditor,
        showQueryEditor,
        showDebugPanel,
        insightDataLoading,
        insightDataError,
    } = useValues(theInsightDataLogic)
    const { toggleQueryEditorPanel, toggleDebugPanel, cancelChanges } = useActions(theInsightDataLogic)

    const { insightMode, dashboardId, filtersOverride, variablesOverride } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    const { createStaticCohort, startExport } = useActions(exportsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openCreateFromInsightModal } = useActions(endpointLogic)
    const { openMetricFromInsightModal } = useActions(metricsLogic)
    // A lazy loader: reading allMetrics fetches the metrics, so read it only for a saved insight.
    const metricsValues = useValues(metricsLogic)
    const { push } = useActions(router)
    const { openTerraformModal, openAddToDashboardModal, saveAndAddToDashboard } = useActions(
        insightModalsLogic(insightLogicProps)
    )

    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { copyImage, downloadImage } = useActions(captureImageLogic)
    const { isCapturing: isCapturingImage } = useValues(captureImageLogic)

    const { user, hasAvailableFeature } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id
    // Collections exist only in the Today navigation.
    const collectionTarget: ShareToSpaceTarget | null =
        isSavedInsight && featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
            ? {
                  type: 'insight',
                  ref: insight.short_id!,
                  name: insight.name || insight.derived_name || 'Untitled insight',
              }
            : null
    // Adding to notebooks is deprecated under the rail redesign.
    const showAddToNotebook = isSavedInsight && !featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
    const addToNotebookAction = useAddToNotebookAction(RESOURCE_TYPE, {
        notebookSelectButtonProps: {
            resource: {
                type: NotebookNodeType.Query,
                attrs: { query: { kind: NodeKind.SavedInsightNode, shortId: insight.short_id } },
            },
        },
    })
    const fileActions = useSceneFileActions(RESOURCE_TYPE)
    const collectionActions = useAnalyticsCollectionActions(collectionTarget, RESOURCE_TYPE)
    const pinActions = useScenePinAction(RESOURCE_TYPE, { section: 'actions' })

    // Creating an export requires editor access to the export resource.
    const exportAssetAccessControlDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor) ?? undefined
    const sharingDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.SharingConfiguration, AccessControlLevel.Viewer) ??
        undefined

    const unsavedSqlQuery = unsavedSqlInsightQuery(query, isSavedInsight)
    const canExport = exportContext != null && insight.short_id != null
    // Only an InsightViz renders the results card the browser-side capture targets. Anything else
    // still goes through the server-side PNG render.
    const canCaptureImage = isInsightVizNode(query)
    const captureTarget = {
        selector: INSIGHT_GRAPH_SELECTOR,
        screenshotKey: INSIGHT_SCREENSHOT_KEY,
        name: insight.name || insight.derived_name || undefined,
    }
    // A browser capture takes whatever is on screen. The results card renders before the chart does, so
    // capturing mid-load or after a failed query produces a valid PNG of an empty card.
    const captureDisabledReason = insightDataLoading
        ? 'Wait for the insight to finish loading'
        : insightDataError
          ? 'The insight has no results to capture'
          : undefined
    const capturingReason = isCapturingImage ? 'Capturing the image' : undefined
    const pngExportDisabledReason = canCaptureImage
        ? (captureDisabledReason ?? capturingReason)
        : exportAssetAccessControlDisabledReason
    const showCohort =
        hogQL != null &&
        (isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query))
    const canShowDebugPanel = isSavedInsight && (user?.is_staff || user?.is_impersonated || preflight?.is_debug)
    const showMetalytics =
        isSavedInsight &&
        metalyticsInstanceId != null &&
        featureFlags['metalytics'] &&
        hasAvailableFeature(AvailableFeature.AUDIT_LOGS)
    const showCreateEndpoint =
        isSavedInsight && !getAccessControlDisabledReason(AccessControlResourceType.Endpoint, AccessControlLevel.Editor)
    // A metric already snapshots this insight, so don't offer to create a duplicate.
    const showCreateMetric =
        isSavedInsight &&
        !metricsValues.allMetrics.some((metric) => metric.source_insight_short_id === insight.short_id)
    // The Today layout pins insights per person instead, so the project-wide favorite would read as a duplicate.
    const showFavorite = isSavedInsight && !featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
    const canCreateAlertForInsight = areAlertsSupportedForInsight(query, {
        metricsAlertsEnabled: !!featureFlags[FEATURE_FLAGS.METRICS],
    })

    const handleToggleQueryEditorPanel = (): void => {
        if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
            setInsightMode(ItemMode.Edit, null)
            if (showQueryEditor) {
                return
            }
        }
        toggleQueryEditorPanel()
    }

    const editing = insightMode === ItemMode.Edit
    const viewingSaved = !editing && isSavedInsight
    const overrideWarning = getOverrideWarningPropsForButton(query, filtersOverride, variablesOverride)
    const overrideWarningTooltip =
        typeof overrideWarning.tooltip === 'function' ? overrideWarning.tooltip() : overrideWarning.tooltip
    const editDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Insight,
            AccessControlLevel.Editor,
            insight.user_access_level
        ) ?? undefined
    const editInsight = (): void =>
        openInsightEditor({
            query,
            insightShortId: insight.short_id,
            dashboardId,
            queryChanged,
            enterEditMode: () => setInsightMode(ItemMode.Edit, null),
        })
    // New insights need a target folder; existing ones save in place.
    const saveInsightToFolder = (redirectToViewMode?: boolean): void => {
        if (insight.short_id) {
            saveInsight(redirectToViewMode)
        } else {
            saveInsight(redirectToViewMode, getLastNewFolder() ?? 'Unfiled/Insights')
        }
    }
    const saveAsNew = (): void => saveAs(undefined, undefined, 'Unfiled/Insights')
    const hasChanges = insightChanged || queryChanged
    const noChanges = hasDashboardItemId && !hasChanges
    const addingToDashboard = !insight.id && !!insight.dashboards?.length
    const saveAsAvailable = hasDashboardItemId && !addingToDashboard
    const savingReason = insightSaving ? 'Saving the insight' : undefined

    const actions: SceneAction[] = [
        ...(showAddToNotebook || showCreateEndpoint || showCreateMetric || showCohort
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-create`,
                      label: 'Create',
                      icon: <IconPlusSmall />,
                      items: [
                          ...(showAddToNotebook ? [addToNotebookAction] : []),
                          ...(showCreateEndpoint
                              ? [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-create-endpoint`,
                                        label: 'Endpoint',
                                        icon: <IconEndpoints />,
                                        opensFloatingUi: true,
                                        onSelect: openCreateFromInsightModal,
                                    },
                                ]
                              : []),
                          ...(showCreateMetric
                              ? [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-create-metric`,
                                        label: 'Metric',
                                        icon: <IconGraph />,
                                        opensFloatingUi: true,
                                        onSelect: openMetricFromInsightModal,
                                    },
                                ]
                              : []),
                          ...(showCohort
                              ? [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-create-cohort`,
                                        label: 'Static cohort',
                                        icon: <IconPeople />,
                                        opensFloatingUi: true,
                                        onSelect: () =>
                                            openSaveAsCohortDialog(createStaticCohort, hogQL!, hogQLVariables),
                                    },
                                ]
                              : []),
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isSavedInsight
            ? ([
                  {
                      group: 'file',
                      section: 'share',
                      id: `${RESOURCE_TYPE}-menubar-add-to-dashboard`,
                      label: 'Add to dashboard',
                      icon: <IconPlusSmall />,
                      opensFloatingUi: true,
                      onSelect: openAddToDashboardModal,
                      pinned: viewingSaved
                          ? {
                                order: 2,
                                variant: 'secondary',
                                render: () => (
                                    <Button
                                        variant="outline"
                                        data-attr="insight-add-to-dashboard-prominent-button"
                                        onClick={() => openAddToDashboardModal()}
                                    >
                                        <IconPlusSmall />
                                        Add to dashboard
                                    </Button>
                                ),
                            }
                          : undefined,
                  },
                  {
                      group: 'file',
                      section: 'share',
                      id: `${RESOURCE_TYPE}-menubar-share`,
                      label: 'Share or embed',
                      icon: <IconShare />,
                      disabledReason: sharingDisabledReason,
                      onSelect: () => push(urls.insightSharing(insight.short_id!)),
                      pinned: viewingSaved ? { order: 1, variant: 'icon', dataAttr: 'insight-share-menu' } : undefined,
                  },
                  {
                      group: 'file',
                      section: 'share',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-monitor`,
                      label: 'Monitor',
                      icon: <IconBell />,
                      items: [
                          {
                              id: `${RESOURCE_TYPE}-menubar-alerts`,
                              label: 'Alerts',
                              icon: <IconWarning />,
                              onSelect: () => push(urls.insightAlerts(insight.short_id!)),
                          },
                          {
                              id: `${RESOURCE_TYPE}-menubar-subscribe`,
                              label: 'Subscriptions',
                              icon: <IconBell />,
                              onSelect: () => push(urlForSubscriptions({ insightShortId: insight.short_id })),
                          },
                      ],
                      pinned: viewingSaved
                          ? {
                                order: 3,
                                variant: 'secondary',
                                render: () => (
                                    <QuillInsightMonitorButton
                                        insightShortId={insight.short_id!}
                                        canCreateAlert={canCreateAlertForInsight}
                                    />
                                ),
                            }
                          : undefined,
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...collectionActions,
        ...(isSavedInsight && canCopyToProject
            ? ([
                  {
                      group: 'file',
                      section: 'project-tree',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      onSelect: () => push(urls.resourceTransfer('Insight', insight.id!, insight.short_id)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canCaptureImage
            ? ([
                  {
                      group: 'file',
                      section: 'project-tree',
                      id: `${RESOURCE_TYPE}-menubar-copy-image`,
                      label: 'Copy as PNG',
                      icon: <IconImage />,
                      disabledReason: captureDisabledReason ?? capturingReason,
                      onSelect: () => copyImage(captureTarget),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'project-tree',
            id: `${RESOURCE_TYPE}-menubar-terraform`,
            label: 'Manage with Terraform',
            icon: <IconCode2 />,
            opensFloatingUi: true,
            onSelect: openTerraformModal,
        },
        ...(canExport
            ? ([
                  {
                      group: 'file',
                      section: 'project-tree',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-export`,
                      label: 'Export',
                      icon: <IconDownload />,
                      items: [
                          {
                              id: `${RESOURCE_TYPE}-menubar-export-png`,
                              label: 'PNG',
                              icon: <IconDownload />,
                              disabledReason: pngExportDisabledReason,
                              onSelect: () =>
                                  canCaptureImage
                                      ? downloadImage(captureTarget)
                                      : startExport({
                                            export_format: ExporterFormat.PNG,
                                            insight: insight.id,
                                            insightShortId: insight.short_id,
                                            export_context: exportContext,
                                        }),
                          },
                          {
                              id: `${RESOURCE_TYPE}-menubar-export-csv`,
                              label: 'CSV',
                              icon: <IconDownload />,
                              disabledReason: exportAssetAccessControlDisabledReason,
                              onSelect: () =>
                                  startExport({ export_format: ExporterFormat.CSV, export_context: exportContext }),
                          },
                          {
                              id: `${RESOURCE_TYPE}-menubar-export-xlsx`,
                              label: 'XLSX',
                              icon: <IconDownload />,
                              disabledReason: exportAssetAccessControlDisabledReason,
                              onSelect: () =>
                                  startExport({ export_format: ExporterFormat.XLSX, export_context: exportContext }),
                          },
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isSavedInsight
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete insight',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason:
                          getAccessControlDisabledReason(
                              AccessControlResourceType.Insight,
                              AccessControlLevel.Editor
                          ) ?? undefined,
                      onSelect: () => deleteInsight(dashboardId ?? null),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!editing && canEditInsight
            ? ([
                  {
                      group: 'edit',
                      section: 'mode',
                      id: `${RESOURCE_TYPE}-menubar-edit-insight`,
                      label: 'Edit',
                      icon: <IconPencil />,
                      tooltip: typeof overrideWarningTooltip === 'string' ? overrideWarningTooltip : undefined,
                      disabledReason: editDisabledReason,
                      onSelect: editInsight,
                      pinned: {
                          order: 5,
                          variant: 'primary',
                          render: () => (
                              <Button
                                  variant="primary"
                                  onClick={editInsight}
                                  tooltip={overrideWarningTooltip}
                                  disabledReason={editDisabledReason}
                                  data-attr="insight-edit-button"
                              >
                                  {overrideWarning.icon}
                                  Edit
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(editing
            ? ([
                  {
                      group: 'edit',
                      section: 'mode',
                      id: `${RESOURCE_TYPE}-menubar-save`,
                      label: addingToDashboard ? 'Save & add to dashboard' : 'Save',
                      disabledReason: noChanges ? 'No changes to save' : savingReason,
                      onSelect: () => saveInsightToFolder(true),
                      pinned: {
                          order: 5,
                          variant: 'primary',
                          render: () => (
                              <QuillInsightSaveButton
                                  saveAs={saveAsNew}
                                  saveInsight={saveInsightToFolder}
                                  isSaved={hasDashboardItemId}
                                  addingToDashboard={addingToDashboard}
                                  insightSaving={insightSaving}
                                  insightChanged={hasChanges}
                                  onSaveAndAddToDashboard={isSavedInsight ? () => saveAndAddToDashboard() : undefined}
                              />
                          ),
                      },
                  },
                  ...(!noChanges
                      ? ([
                            {
                                group: 'edit',
                                section: 'mode',
                                id: `${RESOURCE_TYPE}-menubar-save-and-continue`,
                                label: `${addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing`,
                                disabledReason: savingReason,
                                onSelect: () => saveInsightToFolder(false),
                            },
                        ] satisfies SceneAction[])
                      : []),
                  ...(!noChanges && isSavedInsight
                      ? ([
                            {
                                group: 'edit',
                                section: 'mode',
                                id: `${RESOURCE_TYPE}-menubar-save-and-add-to-dashboard`,
                                label: 'Save & add to dashboard',
                                opensFloatingUi: true,
                                disabledReason: savingReason,
                                onSelect: () => saveAndAddToDashboard(),
                            },
                        ] satisfies SceneAction[])
                      : []),
                  ...(saveAsAvailable
                      ? ([
                            {
                                group: 'edit',
                                section: 'mode',
                                id: `${RESOURCE_TYPE}-menubar-save-as`,
                                label: 'Save as',
                                opensFloatingUi: true,
                                onSelect: saveAsNew,
                            },
                        ] satisfies SceneAction[])
                      : []),
                  ...(hasDashboardItemId
                      ? ([
                            {
                                group: 'edit',
                                section: 'mode',
                                id: `${RESOURCE_TYPE}-menubar-cancel-edit`,
                                label: 'Cancel',
                                keywords: ['discard', 'changes'],
                                onSelect: () => {
                                    cancelChanges()
                                    setInsightMode(ItemMode.View, null)
                                },
                                pinned: {
                                    order: 4,
                                    variant: 'secondary',
                                    render: () => (
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
                                    ),
                                },
                            },
                        ] satisfies SceneAction[])
                      : []),
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'actions',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            disabledReason: insightDuplicating ? 'Duplicating…' : undefined,
            onSelect: () => duplicateInsight(insight as InsightModel, true),
        },
        ...(canEditInSqlEditor || unsavedSqlQuery
            ? ([
                  {
                      group: 'edit',
                      section: 'actions',
                      id: `${RESOURCE_TYPE}-menubar-edit-sql`,
                      label: 'Edit in SQL editor',
                      icon: <IconPencil />,
                      onSelect: () =>
                          push(
                              urls.sqlEditor({
                                  query: unsavedSqlQuery ?? hogQL ?? undefined,
                                  dashboard: unsavedSqlQuery ? (dashboardId ?? undefined) : undefined,
                              })
                          ),
                  },
              ] satisfies SceneAction[])
            : []),
        ...pinActions,
        ...(showFavorite
            ? ([
                  {
                      group: 'edit',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-favorite`,
                      label: 'Favorite',
                      checked: !!insight.favorited,
                      onCheckedChange: (checked) => setInsightMetadata({ favorited: checked }),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-view-source`,
            label: 'View source',
            checked: showQueryEditor,
            onCheckedChange: handleToggleQueryEditorPanel,
        },
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <>
                    <SceneTagsCombobox
                        onSave={(tags) => setInsightMetadata({ tags })}
                        tags={insight.tags}
                        dataAttrKey={RESOURCE_TYPE}
                        canEdit={canEditInsight}
                        loading={isSavingTags}
                    />
                    <SceneActivityIndicator
                        at={insight.last_modified_at}
                        by={insight.last_modified_by}
                        prefix="Last modified"
                    />
                    {showMetalytics && (
                        <Button
                            type="button"
                            variant="default"
                            size="sm"
                            left
                            onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                            data-attr={`${RESOURCE_TYPE}-menubar-metalytics`}
                        >
                            <IconPulse />
                            View metalytics
                        </Button>
                    )}
                </>
            ),
        },
        ...(canShowDebugPanel
            ? ([
                  {
                      group: 'staff',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-debug-panel`,
                      label: 'Show debug panel',
                      checked: showDebugPanel,
                      onCheckedChange: toggleDebugPanel,
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return (
        <>
            <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
            {collectionTarget && <AnalyticsCollectionDialogHost target={collectionTarget} />}
        </>
    )
}

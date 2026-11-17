import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconSparkles, IconUpload } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MAX_LISTED_IMPORTS, importStatusLine } from './components/MetricsDashboardActions'
import { QuillMetricsDashboardActions } from './components/QuillMetricsDashboardActions'
import { metricsDashboardImportLogic } from './dashboardImport/metricsDashboardImportLogic'
import { DISMISS_SUGGESTION_LABEL } from './suggestedDashboards/dismissSuggestionLabel'
import { suggestedDashboardsLogic } from './suggestedDashboards/suggestedDashboardsLogic'

const RESOURCE_TYPE = 'metrics'

interface MetricsSceneMenuBarProps {
    onFeedbackClick: () => void
}

export function MetricsSceneMenuBar(props: MetricsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    const suggestionsEnabled = useFeatureFlag('METRICS_SUGGESTED_DASHBOARDS')
    if (!enabled) {
        return null
    }
    // The suggestions logic loads on mount, so it mounts only behind its flag.
    return suggestionsEnabled ? (
        <MetricsSceneMenuBarWithSuggestions {...props} />
    ) : (
        <MetricsSceneMenuBarInner {...props} suggestionActions={[]} />
    )
}

function MetricsSceneMenuBarWithSuggestions(props: MetricsSceneMenuBarProps): JSX.Element {
    const { visibleSuggestions: suggestions, openingId } = useValues(suggestedDashboardsLogic)
    const { openSuggestion, dismissSuggestion, menuOpened } = useActions(suggestedDashboardsLogic)
    const { user } = useValues(userLogic)
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor) ??
        undefined

    const suggestionActions: SceneAction[] =
        suggestions === null || (suggestions.length === 0 && !user?.is_staff)
            ? []
            : [
                  {
                      group: 'file',
                      section: 'dashboards',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-suggested-dashboards`,
                      label: 'Suggested dashboards',
                      icon: <IconSparkles className="text-ai" />,
                      onOpenChange: (open) => {
                          if (open) {
                              menuOpened()
                          }
                      },
                      items: [
                          ...suggestions.map((suggestion) => {
                              const created = suggestion.dashboard_id !== null
                              return {
                                  id: `${RESOURCE_TYPE}-menubar-suggested-dashboard-${suggestion.id}`,
                                  dataAttr: 'metrics-suggested-dashboard',
                                  label: suggestion.name,
                                  section: 'open',
                                  tooltip: created ? 'Created. Open the dashboard.' : undefined,
                                  disabledReason: created
                                      ? undefined
                                      : openingId === suggestion.id
                                        ? 'Creating the dashboard'
                                        : disabledReason,
                                  onSelect: () => openSuggestion(suggestion),
                              }
                          }),
                          ...suggestions.map((suggestion) => ({
                              id: `${RESOURCE_TYPE}-menubar-suggested-dashboard-dismiss-${suggestion.id}`,
                              dataAttr: 'metrics-suggested-dashboard-dismiss',
                              label: `${DISMISS_SUGGESTION_LABEL}: ${suggestion.name}`,
                              section: 'dismiss',
                              disabledReason,
                              onSelect: () => dismissSuggestion(suggestion),
                          })),
                          ...(user?.is_staff
                              ? [
                                    {
                                        id: 'metrics-suggested-dashboards-review',
                                        label: 'Review generated dashboards',
                                        section: 'review',
                                        onSelect: () => router.actions.push(urls.metricsDashboardReview()),
                                    },
                                ]
                              : []),
                      ],
                  },
              ]

    return <MetricsSceneMenuBarInner {...props} suggestionActions={suggestionActions} />
}

function MetricsSceneMenuBarInner({
    onFeedbackClick,
    suggestionActions,
}: MetricsSceneMenuBarProps & { suggestionActions: SceneAction[] }): JSX.Element {
    const { recentImports, runningImports } = useValues(metricsDashboardImportLogic)
    const { openImportModal, openImport } = useActions(metricsDashboardImportLogic)
    const importEnabled = useFeatureFlag('METRICS_DASHBOARD_IMPORT')
    const importDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ??
        getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor) ??
        undefined
    // The tab bar shows these menus in a wide scene, so the title row shows them only in a narrow one.
    const dashboardActionsPin = {
        order: 1,
        variant: 'secondary' as const,
        render: () => (
            <div className="@min-[48rem]/metrics-scene:hidden">
                <QuillMetricsDashboardActions />
            </div>
        ),
    }

    const actions: SceneAction[] = [
        ...(importEnabled
            ? ([
                  {
                      group: 'file',
                      section: 'dashboards',
                      type: 'submenu',
                      id: 'metrics-dashboard-import-menu',
                      label: 'Import',
                      icon: <IconUpload />,
                      disabledReason: importDisabledReason,
                      tooltip: runningImports.length
                          ? `${runningImports.length} ${runningImports.length === 1 ? 'import is' : 'imports are'} running`
                          : undefined,
                      items: [
                          {
                              id: 'metrics-dashboard-import-grafana',
                              label: 'Import from Grafana',
                              opensFloatingUi: true,
                              onSelect: () => openImportModal('grafana'),
                          },
                          {
                              id: 'metrics-dashboard-import-screenshot',
                              label: 'Import from screenshot',
                              opensFloatingUi: true,
                              onSelect: () => openImportModal('screenshot'),
                          },
                          ...recentImports.slice(0, MAX_LISTED_IMPORTS).map((dashboardImport, index) => ({
                              id: `metrics-dashboard-import-recent-${dashboardImport.id ?? index}`,
                              dataAttr: 'metrics-dashboard-import-recent',
                              section: 'recent',
                              label: `${dashboardImport.dashboard_name} (${importStatusLine(dashboardImport)})`,
                              opensFloatingUi: true,
                              onSelect: () => openImport(dashboardImport),
                          })),
                      ],
                      pinned: dashboardActionsPin,
                  },
              ] satisfies SceneAction[])
            : []),
        ...suggestionActions.map((action) => (importEnabled ? action : { ...action, pinned: dashboardActionsPin })),
        {
            group: 'file',
            section: 'feedback',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconFeedback />,
            opensFloatingUi: true,
            onSelect: onFeedbackClick,
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

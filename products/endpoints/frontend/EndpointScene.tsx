import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    IconCheck,
    IconClock,
    IconCode,
    IconCode2,
    IconDatabase,
    IconDecisionTree,
    IconEndpoints,
    IconGear,
    IconGraph,
    IconLive,
    IconPause,
    IconPlay,
    IconPlayFilled,
    IconPlusSmall,
    IconPulse,
    IconRewind,
    IconServer,
    IconTrash,
} from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ScenePanel, ScenePanelActionsSection, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, EndpointType, EndpointVersionType } from '~/types'

import { EndpointConfiguration } from './endpoint-tabs/EndpointConfiguration'
import { EndpointLineage } from './endpoint-tabs/EndpointLineage'
import { EndpointLogs } from './endpoint-tabs/EndpointLogs'
import { EndpointOverview } from './endpoint-tabs/EndpointOverview'
import { EndpointPlayground } from './endpoint-tabs/EndpointPlayground'
import { EndpointQuery } from './endpoint-tabs/EndpointQuery'
import { EndpointVersions } from './endpoint-tabs/EndpointVersions'
import { VersionBanner } from './endpoint-tabs/VersionBanner'
import { EndpointSceneHeader } from './EndpointHeader'
import { endpointLogic } from './endpointLogic'
import { EndpointTab, endpointSceneLogic } from './endpointSceneLogic'
import { EndpointSceneSkeleton } from './EndpointSceneSkeleton'
import { endpointsLogic } from './endpointsLogic'
import { insightPickerEndpointModalLogic } from './insightPickerEndpointModalLogic'
import { useEndpointChangeActions } from './useEndpointChangeActions'

export const scene: SceneExport = {
    component: EndpointScene,
    logic: endpointSceneLogic,
    productKey: ProductKey.ENDPOINTS,
}

export function EndpointScene(): JSX.Element {
    const { endpoint, endpointLoading, endpointMissing, activeTab, viewingVersion, isMaterialized } =
        useValues(endpointSceneLogic)
    const { setViewingVersion, toggleMaterializationFromMenu } = useActions(endpointSceneLogic)
    const { deleteEndpoint, confirmToggleActive, saveTagsInline } = useActions(endpointLogic)
    const { versions } = useValues(endpointLogic)
    const { allEndpoints } = useValues(endpointsLogic)
    const { openModal } = useActions(insightPickerEndpointModalLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const lineageSavedQueryId = (viewingVersion ?? endpoint)?.materialization?.saved_query_id ?? null
    const visibleTab =
        activeTab === EndpointTab.LINEAGE && endpoint && !lineageSavedQueryId ? EndpointTab.QUERY : activeTab
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const fileActions = useSceneFileActions('endpoint')
    const changeActions = useEndpointChangeActions()

    if (endpointMissing) {
        return <NotFound object="endpoint" />
    }

    const tabs: LemonTab<EndpointTab>[] = [
        {
            key: EndpointTab.QUERY,
            label: 'Query',
            'data-attr': 'endpoint-query-tab',
            content: <EndpointQuery />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.QUERY }).url
                : undefined,
        },
        {
            key: EndpointTab.CONFIGURATION,
            label: 'Configuration',
            'data-attr': 'endpoint-configuration-tab',
            content: <EndpointConfiguration />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.CONFIGURATION }).url
                : undefined,
        },
        {
            key: EndpointTab.VERSIONS,
            label: 'Versions',
            content: <EndpointVersions />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.VERSIONS }).url
                : undefined,
        },
        {
            key: EndpointTab.PLAYGROUND,
            label: 'Playground',
            'data-attr': 'endpoint-playground-tab',
            content: <EndpointPlayground />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.PLAYGROUND }).url
                : undefined,
        },
        {
            key: EndpointTab.LOGS,
            label: 'Logs',
            'data-attr': 'endpoint-logs-tab',
            content: <EndpointLogs />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.LOGS }).url
                : undefined,
        },
        ...(lineageSavedQueryId
            ? [
                  {
                      key: EndpointTab.LINEAGE,
                      label: 'Lineage',
                      'data-attr': 'endpoint-lineage-tab',
                      content: <EndpointLineage savedQueryId={lineageSavedQueryId} />,
                      link: endpoint
                          ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.LINEAGE }).url
                          : undefined,
                  },
              ]
            : []),
        {
            key: EndpointTab.HISTORY,
            label: 'History',
            'data-attr': 'endpoint-history-tab',
            content: endpoint ? (
                <ActivityLog scope={[ActivityScope.ENDPOINT, ActivityScope.ENDPOINT_VERSION]} id={endpoint.id} />
            ) : (
                <></>
            ),
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.HISTORY }).url
                : undefined,
        },
    ]

    const handleDelete = (): void => {
        if (!endpoint?.name) {
            return
        }

        LemonDialog.open({
            title: 'Delete endpoint?',
            content: (
                <div className="text-sm text-secondary">
                    Are you sure you want to delete this endpoint? This action cannot be undone.
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => {
                    deleteEndpoint(endpoint.name)
                },
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const handleToggleActive = (): void => {
        if (!endpoint) {
            return
        }
        confirmToggleActive(endpoint)
    }

    const renderTabContent = (): JSX.Element => {
        if (!endpoint) {
            return <></>
        }
        switch (visibleTab) {
            case EndpointTab.CONFIGURATION:
                return <EndpointConfiguration />
            case EndpointTab.VERSIONS:
                return <EndpointVersions />
            case EndpointTab.PLAYGROUND:
                return <EndpointPlayground />
            case EndpointTab.LOGS:
                return <EndpointLogs />
            case EndpointTab.LINEAGE:
                return lineageSavedQueryId ? <EndpointLineage savedQueryId={lineageSavedQueryId} /> : <></>
            case EndpointTab.HISTORY:
                return <ActivityLog scope={[ActivityScope.ENDPOINT, ActivityScope.ENDPOINT_VERSION]} id={endpoint.id} />
            case EndpointTab.QUERY:
            default:
                return <EndpointQuery />
        }
    }

    return (
        <BindLogic logic={endpointSceneLogic} props={{}}>
            <SceneContent className="Endpoint">
                {sceneMenuBarEnabled && endpoint && (
                    <SceneActions
                        actions={[
                            ...buildEndpointFileActions({
                                endpoint,
                                allEndpoints,
                                versions,
                                viewingVersion,
                                setViewingVersion,
                                lineageSavedQueryId,
                                openNewFromInsight: openModal,
                            }),
                            ...fileActions,
                            ...changeActions,
                            ...buildEndpointEditActions({
                                endpoint,
                                viewingVersion,
                                isMaterialized,
                                toggleActive: handleToggleActive,
                                toggleMaterialization: toggleMaterializationFromMenu,
                                remove: handleDelete,
                            }),
                            {
                                group: 'metadata',
                                type: 'panel',
                                id: 'endpoint-menubar-metadata',
                                label: 'Metadata',
                                render: () => (
                                    <SceneTagsCombobox
                                        onSave={(tags) => saveTagsInline(tags)}
                                        canEdit
                                        tags={endpoint.tags}
                                        dataAttrKey="endpoint"
                                    />
                                ),
                            },
                        ]}
                        dataAttrKey="endpoint"
                    />
                )}
                <EndpointSceneHeader />
                {endpoint && !endpoint.is_active && (
                    <LemonBanner type="error">
                        This endpoint is deactivated and cannot be accessed via the API. <br />
                        This applies to all versions, even if they're active - endpoint status overrules version status.
                    </LemonBanner>
                )}
                {viewingVersion && endpoint && (
                    <VersionBanner
                        version={viewingVersion}
                        currentVersion={endpoint.current_version}
                        onGoToLatest={() => setViewingVersion(null)}
                    />
                )}
                {endpointLoading && !endpoint ? (
                    <EndpointSceneSkeleton showTabs={!sceneMenuBarEnabled} />
                ) : (
                    <>
                        <EndpointOverview />
                        {sceneMenuBarEnabled ? renderTabContent() : <LemonTabs activeKey={visibleTab} tabs={tabs} />}
                    </>
                )}
            </SceneContent>
            {endpoint && (
                <ScenePanel>
                    <ScenePanelInfoSection>
                        <SceneTags
                            tags={endpoint.tags}
                            onSave={(tags) => saveTagsInline(tags)}
                            canEdit
                            dataAttrKey="endpoint"
                        />
                    </ScenePanelInfoSection>
                    <ScenePanelActionsSection>
                        <ButtonPrimitive menuItem onClick={handleToggleActive}>
                            {endpoint.is_active ? <IconPause /> : <IconPlay />}
                            {endpoint.is_active ? 'Deactivate endpoint' : 'Activate endpoint'}
                        </ButtonPrimitive>
                        <LemonDivider />
                        <ButtonPrimitive menuItem onClick={handleDelete} className="text-danger">
                            <IconTrash />
                            Delete endpoint
                        </ButtonPrimitive>
                    </ScenePanelActionsSection>
                </ScenePanel>
            )}
        </BindLogic>
    )
}

const pushTab = (endpointName: string, tab: EndpointTab): void =>
    router.actions.push(combineUrl(urls.endpoint(endpointName), { tab }).url)

function buildEndpointFileActions({
    endpoint,
    allEndpoints,
    versions,
    viewingVersion,
    setViewingVersion,
    lineageSavedQueryId,
    openNewFromInsight,
}: {
    endpoint: EndpointType
    allEndpoints: { name: string }[]
    versions: EndpointVersionType[]
    viewingVersion: EndpointVersionType | null
    setViewingVersion: (version: EndpointVersionType | null) => void
    lineageSavedQueryId: string | null
    openNewFromInsight: () => void
}): SceneAction[] {
    const otherEndpoints = allEndpoints
        .filter((e) => e.name !== endpoint.name)
        .sort((a, b) => a.name.localeCompare(b.name))
    const sortedVersions = [...versions].sort((a, b) => b.version - a.version)
    const effectiveVersion = viewingVersion?.version ?? endpoint.current_version

    return [
        {
            group: 'file',
            section: 'open',
            type: 'submenu',
            id: 'endpoint-menubar-new-endpoint',
            label: 'New endpoint',
            items: [
                {
                    id: 'endpoint-menubar-new-sql',
                    label: 'From SQL editor',
                    icon: <IconServer />,
                    onSelect: () => router.actions.push(urls.sqlEditor({ source: 'endpoint' })),
                },
                {
                    id: 'endpoint-menubar-new-insight',
                    label: 'From insight',
                    icon: <IconGraph />,
                    opensFloatingUi: true,
                    onSelect: openNewFromInsight,
                },
            ],
        },
        {
            group: 'file',
            section: 'open',
            type: 'submenu',
            id: 'endpoint-menubar-open-endpoint',
            label: 'Open endpoint',
            items: [
                ...(otherEndpoints.length === 0
                    ? [
                          {
                              id: 'endpoint-menubar-no-other-endpoints',
                              section: 'endpoints',
                              label: 'No other endpoints',
                              icon: <IconEndpoints />,
                              disabledReason: 'This project has no other endpoints',
                              onSelect: () => {},
                          },
                      ]
                    : otherEndpoints.map((e) => ({
                          id: `endpoint-menubar-open-${e.name}`,
                          section: 'endpoints',
                          label: e.name,
                          icon: <IconEndpoints />,
                          onSelect: () => router.actions.push(urls.endpoint(e.name)),
                      }))),
                {
                    id: 'endpoint-menubar-browse-endpoints',
                    section: 'browse',
                    label: 'Browse all endpoints',
                    icon: <IconPlusSmall />,
                    onSelect: () => router.actions.push(urls.endpoints()),
                },
            ],
        },
        {
            group: 'file',
            section: 'open',
            type: 'submenu',
            id: 'endpoint-menubar-open-version',
            label: 'Open version',
            items: [
                ...(sortedVersions.length === 0
                    ? [
                          {
                              id: 'endpoint-menubar-no-versions',
                              section: 'versions',
                              label: 'No versions yet',
                              icon: <IconRewind />,
                              disabledReason: 'This endpoint has no versions yet',
                              onSelect: () => {},
                          },
                      ]
                    : sortedVersions.map((v) => {
                          const isCurrent = v.version === endpoint.current_version
                          return {
                              id: `endpoint-menubar-open-version-${v.version}`,
                              section: 'versions',
                              label: `v${v.version}${isCurrent ? ' (latest)' : ''}`,
                              icon: v.version === effectiveVersion ? <IconCheck /> : <IconRewind />,
                              onSelect: () => setViewingVersion(isCurrent ? null : v),
                          }
                      })),
                {
                    id: 'endpoint-menubar-view-all-versions',
                    section: 'manage',
                    label: 'Manage versions',
                    icon: <IconCode2 />,
                    onSelect: () => pushTab(endpoint.name, EndpointTab.VERSIONS),
                },
            ],
        },
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-open-query',
            label: 'Open query',
            icon: <IconCode />,
            onSelect: () => router.actions.push(urls.endpoint(endpoint.name)),
        },
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-open-configuration',
            label: 'Open configuration',
            icon: <IconGear />,
            onSelect: () => pushTab(endpoint.name, EndpointTab.CONFIGURATION),
        },
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-open-playground',
            label: 'Open playground',
            icon: <IconPlayFilled />,
            onSelect: () => pushTab(endpoint.name, EndpointTab.PLAYGROUND),
        },
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-view-logs',
            label: 'View logs',
            icon: <IconLive />,
            onSelect: () => pushTab(endpoint.name, EndpointTab.LOGS),
        },
        ...(lineageSavedQueryId
            ? ([
                  {
                      group: 'file',
                      section: 'navigate',
                      id: 'endpoint-menubar-view-lineage',
                      label: 'View lineage',
                      icon: <IconDecisionTree />,
                      onSelect: () => pushTab(endpoint.name, EndpointTab.LINEAGE),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-view-history',
            label: 'View history',
            icon: <IconClock />,
            onSelect: () => pushTab(endpoint.name, EndpointTab.HISTORY),
        },
        {
            group: 'file',
            section: 'navigate',
            id: 'endpoint-menubar-view-usage',
            label: 'View usage',
            icon: <IconPulse />,
            onSelect: () => router.actions.push(urls.endpointsUsage({ endpointFilter: [endpoint.name] })),
        },
    ]
}

function buildEndpointEditActions({
    endpoint,
    viewingVersion,
    isMaterialized,
    toggleActive,
    toggleMaterialization,
    remove,
}: {
    endpoint: EndpointType
    viewingVersion: EndpointVersionType | null
    isMaterialized: boolean | null
    toggleActive: () => void
    toggleMaterialization: () => void
    remove: () => void
}): SceneAction[] {
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
    const hasUnsavedToggle = isMaterialized !== null && isMaterialized !== baseIsMaterialized
    const effective = isMaterialized ?? baseIsMaterialized

    return [
        {
            group: 'edit',
            section: 'state',
            id: 'endpoint-menubar-active-toggle',
            label: endpoint.is_active ? 'Deactivate endpoint' : 'Activate endpoint',
            icon: endpoint.is_active ? <IconPause /> : <IconPlay />,
            onSelect: toggleActive,
        },
        {
            group: 'edit',
            section: 'state',
            id: 'endpoint-menubar-materialize-toggle',
            label: effective ? 'Disable materialization' : 'Materialize endpoint',
            icon: <IconDatabase />,
            disabledReason: hasUnsavedToggle ? 'Save or discard the materialization change first' : undefined,
            onSelect: toggleMaterialization,
        },
        {
            group: 'file',
            section: 'delete',
            id: 'endpoint-menubar-delete',
            label: 'Delete endpoint',
            icon: <IconTrash />,
            destructive: true,
            onSelect: remove,
        },
    ]
}

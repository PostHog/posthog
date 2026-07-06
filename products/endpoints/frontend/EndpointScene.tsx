import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    IconCheck,
    IconClock,
    IconCode2,
    IconDatabase,
    IconEndpoints,
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
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { FEATURE_FLAGS } from 'lib/constants'
import 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { ScenePanel, ScenePanelActionsSection, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, EndpointVersionType } from '~/types'

import { EndpointConfiguration } from './endpoint-tabs/EndpointConfiguration'
import { EndpointLogs } from './endpoint-tabs/EndpointLogs'
import { EndpointOverview } from './endpoint-tabs/EndpointOverview'
import { EndpointPlayground } from './endpoint-tabs/EndpointPlayground'
import { EndpointQuery } from './endpoint-tabs/EndpointQuery'
import { EndpointVersions } from './endpoint-tabs/EndpointVersions'
import { VersionBanner } from './endpoint-tabs/VersionBanner'
import { EndpointSceneHeader } from './EndpointHeader'
import { endpointLogic } from './endpointLogic'
import { EndpointTab, endpointSceneLogic } from './endpointSceneLogic'
import { endpointsLogic } from './endpointsLogic'
import { insightPickerEndpointModalLogic } from './insightPickerEndpointModalLogic'

export const scene: SceneExport = {
    component: EndpointScene,
    logic: endpointSceneLogic,
    productKey: ProductKey.ENDPOINTS,
}

export function EndpointScene(): JSX.Element {
    const { endpoint, endpointLoading, activeTab, viewingVersion, isMaterialized } = useValues(endpointSceneLogic)
    const { setViewingVersion, toggleMaterializationFromMenu } = useActions(endpointSceneLogic)
    const { deleteEndpoint, confirmToggleActive, saveTagsInline } = useActions(endpointLogic)
    const { versions } = useValues(endpointLogic)
    const { allEndpoints } = useValues(endpointsLogic)
    const { openModal } = useActions(insightPickerEndpointModalLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

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
                    router.actions.push(urls.endpoints())
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
        switch (activeTab) {
            case EndpointTab.CONFIGURATION:
                return <EndpointConfiguration />
            case EndpointTab.VERSIONS:
                return <EndpointVersions />
            case EndpointTab.PLAYGROUND:
                return <EndpointPlayground />
            case EndpointTab.LOGS:
                return <EndpointLogs />
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
                    <SceneMenuBar>
                        <SceneMenuBarMenu label="File" dataAttr="endpoint-menubar-file">
                            <SceneMenuBarSubMenu label="New endpoint">
                                <SceneMenuBarItem
                                    onClick={() => router.actions.push(urls.sqlEditor({ source: 'endpoint' }))}
                                    data-attr="endpoint-menubar-new-sql"
                                >
                                    <IconServer />
                                    From SQL editor
                                </SceneMenuBarItem>
                                <SceneMenuBarItem
                                    opensFloatingUi
                                    onClick={openModal}
                                    data-attr="endpoint-menubar-new-insight"
                                >
                                    <IconGraph />
                                    From insight
                                </SceneMenuBarItem>
                            </SceneMenuBarSubMenu>
                            <OpenEndpointSubMenu allEndpoints={allEndpoints} currentEndpointName={endpoint.name} />
                            <OpenVersionSubMenu
                                versions={versions}
                                endpointName={endpoint.name}
                                currentVersion={endpoint.current_version}
                                viewingVersion={viewingVersion}
                                setViewingVersion={setViewingVersion}
                            />
                            <SceneMenuBarSeparator />
                            <SceneMenuBarItem
                                onClick={() =>
                                    router.actions.push(
                                        combineUrl(urls.endpoint(endpoint.name), { tab: EndpointTab.PLAYGROUND }).url
                                    )
                                }
                                data-attr="endpoint-menubar-open-playground"
                            >
                                <IconPlayFilled />
                                Open playground
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                onClick={() =>
                                    router.actions.push(
                                        combineUrl(urls.endpoint(endpoint.name), { tab: EndpointTab.LOGS }).url
                                    )
                                }
                                data-attr="endpoint-menubar-view-logs"
                            >
                                <IconLive />
                                View logs
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                onClick={() =>
                                    router.actions.push(
                                        combineUrl(urls.endpoint(endpoint.name), { tab: EndpointTab.HISTORY }).url
                                    )
                                }
                                data-attr="endpoint-menubar-view-history"
                            >
                                <IconClock />
                                View history
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                onClick={() =>
                                    router.actions.push(urls.endpointsUsage({ endpointFilter: [endpoint.name] }))
                                }
                                data-attr="endpoint-menubar-view-usage"
                            >
                                <IconPulse />
                                View usage
                            </SceneMenuBarItem>
                            <SceneMenuBarSeparator />
                            <SceneMenuBarFileItems dataAttrKey="endpoint" />
                        </SceneMenuBarMenu>
                        <SceneMenuBarMenu label="Edit" dataAttr="endpoint-menubar-edit">
                            <SceneMenuBarItem onClick={handleToggleActive} data-attr="endpoint-menubar-active-toggle">
                                {endpoint.is_active ? <IconPause /> : <IconPlay />}
                                {endpoint.is_active ? 'Deactivate endpoint' : 'Activate endpoint'}
                            </SceneMenuBarItem>
                            {(() => {
                                const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
                                const hasUnsavedToggle =
                                    isMaterialized !== null && isMaterialized !== baseIsMaterialized
                                const effective = isMaterialized ?? baseIsMaterialized
                                return (
                                    <SceneMenuBarItem
                                        onClick={toggleMaterializationFromMenu}
                                        disabled={hasUnsavedToggle}
                                        data-attr="endpoint-menubar-materialize-toggle"
                                    >
                                        <IconDatabase />
                                        {effective ? 'Disable materialization' : 'Materialize endpoint'}
                                    </SceneMenuBarItem>
                                )
                            })()}
                            <SceneMenuBarSeparator />
                            <SceneMenuBarItem
                                variant="destructive"
                                opensFloatingUi
                                onClick={handleDelete}
                                data-attr="endpoint-menubar-delete"
                            >
                                <IconTrash />
                                Delete endpoint
                            </SceneMenuBarItem>
                        </SceneMenuBarMenu>
                        <SceneMenuBarPopover label="Metadata" dataAttr="endpoint-menubar-metadata">
                            <SceneTagsCombobox
                                onSave={(tags) => saveTagsInline(tags)}
                                canEdit
                                tags={endpoint.tags}
                                tagsAvailable={tagsAvailable.filter((t: string) => !endpoint.tags?.includes(t))}
                                dataAttrKey="endpoint"
                            />
                        </SceneMenuBarPopover>
                    </SceneMenuBar>
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
                {!endpointLoading && <EndpointOverview />}
                {sceneMenuBarEnabled ? renderTabContent() : <LemonTabs activeKey={activeTab} tabs={tabs} />}
            </SceneContent>
            {endpoint && (
                <ScenePanel>
                    <ScenePanelInfoSection>
                        <SceneTags
                            tags={endpoint.tags}
                            tagsAvailable={tagsAvailable.filter((t: string) => !endpoint.tags?.includes(t))}
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

function OpenEndpointSubMenu({
    allEndpoints,
    currentEndpointName,
}: {
    allEndpoints: { name: string }[]
    currentEndpointName: string
}): JSX.Element {
    const others = allEndpoints
        .filter((e) => e.name !== currentEndpointName)
        .sort((a, b) => a.name.localeCompare(b.name))
    return (
        <SceneMenuBarSubMenu label="Open endpoint">
            {others.length === 0 ? (
                <SceneMenuBarItem disabled>
                    <IconEndpoints />
                    No other endpoints
                </SceneMenuBarItem>
            ) : (
                others.map((e) => (
                    <SceneMenuBarItem
                        key={e.name}
                        onClick={() => router.actions.push(urls.endpoint(e.name))}
                        data-attr={`endpoint-menubar-open-${e.name}`}
                    >
                        <IconEndpoints />
                        {e.name}
                    </SceneMenuBarItem>
                ))
            )}
            <SceneMenuBarSeparator />
            <SceneMenuBarItem
                onClick={() => router.actions.push(urls.endpoints())}
                data-attr="endpoint-menubar-browse-endpoints"
            >
                <IconPlusSmall />
                Browse all endpoints
            </SceneMenuBarItem>
        </SceneMenuBarSubMenu>
    )
}

function OpenVersionSubMenu({
    versions,
    endpointName,
    currentVersion,
    viewingVersion,
    setViewingVersion,
}: {
    versions: EndpointVersionType[]
    endpointName: string
    currentVersion: number
    viewingVersion: EndpointVersionType | null
    setViewingVersion: (version: EndpointVersionType | null) => void
}): JSX.Element {
    const effectiveVersion = viewingVersion?.version ?? currentVersion
    const sorted = [...versions].sort((a, b) => b.version - a.version)
    return (
        <SceneMenuBarSubMenu label="Open version">
            {sorted.length === 0 ? (
                <SceneMenuBarItem disabled>
                    <IconRewind />
                    No versions yet
                </SceneMenuBarItem>
            ) : (
                sorted.map((v) => {
                    const isCurrent = v.version === currentVersion
                    const isSelected = v.version === effectiveVersion
                    return (
                        <SceneMenuBarItem
                            key={v.version}
                            onClick={() => setViewingVersion(isCurrent ? null : v)}
                            data-attr={`endpoint-menubar-open-version-${v.version}`}
                        >
                            {isSelected ? <IconCheck /> : <IconRewind />}v{v.version}
                            {isCurrent ? ' (latest)' : ''}
                        </SceneMenuBarItem>
                    )
                })
            )}
            <SceneMenuBarSeparator />
            <SceneMenuBarItem
                onClick={() =>
                    router.actions.push(combineUrl(urls.endpoint(endpointName), { tab: EndpointTab.VERSIONS }).url)
                }
                data-attr="endpoint-menubar-view-all-versions"
            >
                <IconCode2 />
                Manage versions
            </SceneMenuBarItem>
        </SceneMenuBarSubMenu>
    )
}

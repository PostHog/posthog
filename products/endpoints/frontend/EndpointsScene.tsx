import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { Endpoints } from './Endpoints'
import { EndpointsUsage } from './EndpointsUsage'
import { endpointsLogic } from './endpointsLogic'
import { endpointsUsageLogic } from './endpointsUsageLogic'
import { OverlayForNewEndpointMenu } from './newEndpointMenu'

const ENDPOINTS_PRODUCT_DESCRIPTION =
    'Create reusable SQL queries and expose them as API endpoints. Query your data programmatically from any application. Note: Endpoints is in beta - features and APIs may change.'
const ENDPOINTS_USAGE_PRODUCT_DESCRIPTION =
    'Monitor endpoint execution metrics including bytes read, CPU usage, and query duration. Compare materialized vs inline executions.'

export const scene: SceneExport = {
    component: EndpointsScene,
    logic: endpointsLogic,
}

export function EndpointsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { activeTab } = useValues(endpointsLogic({ tabId: tabId || '' }))

    const tabs: LemonTab<string>[] = [
        {
            key: 'endpoints',
            label: 'Endpoints',
            content: <Endpoints tabId={tabId || ''} />,
            link: urls.endpoints(),
        },
        {
            key: 'usage',
            label: 'Usage',
            content: <EndpointsUsage tabId={tabId || ''} />,
            link: urls.endpointsUsage(),
        },
    ]
    return (
        <BindLogic logic={endpointsUsageLogic} props={{ key: 'endpointsUsageScene', tabId: tabId || '' }}>
            <BindLogic logic={endpointsLogic} props={{ key: 'endpointsLogic', tabId: tabId || '' }}>
                <BindLogic logic={endpointsUsageLogic} props={{ key: 'endpointsUsageLogic', tabId: tabId || '' }}>
                    <SceneContent>
                        <SceneTitleSection
                            name={sceneConfigurations[Scene.EndpointsScene].name}
                            description={sceneConfigurations[Scene.EndpointsScene].description}
                            resourceType={{
                                type: sceneConfigurations[Scene.EndpointsScene].iconType || 'default_icon_type',
                            }}
                            actions={
                                <AppShortcut
                                    name="EndpointsNew"
                                    keybind={[keyBinds.new]}
                                    intent="New endpoint"
                                    interaction="click"
                                    scope={Scene.EndpointsScene}
                                >
                                    <LemonButton
                                        type="primary"
                                        to={urls.sqlEditor(
                                            undefined,
                                            undefined,
                                            undefined,
                                            undefined,
                                            OutputTab.Endpoint
                                        )}
                                        sideAction={{
                                            dropdown: {
                                                placement: 'bottom-end',
                                                className: 'new-endpoint-overlay',
                                                actionable: true,
                                                overlay: <OverlayForNewEndpointMenu dataAttr="new-endpoint-option" />,
                                            },
                                            'data-attr': 'new-endpoint-dropdown',
                                        }}
                                        data-attr="new-endpoint-button"
                                        size="small"
                                        icon={<IconPlusSmall />}
                                    >
                                        New
                                    </LemonButton>
                                </AppShortcut>
                            }
                        />
                        <LemonBanner
                            type="warning"
                            dismissKey="endpoints-beta-banner"
                            action={{ children: 'Send feedback', id: 'endpoints-feedback-button' }}
                        >
                            <p>
                                Endpoints is in beta and it may not be fully reliable. We are actively working on it and
                                it may change while we work with you on what works best. Please let us know what you'd
                                like to see here and/or report any issues directly to us!
                            </p>
                        </LemonBanner>
                        <ProductIntroduction
                            productName="endpoints"
                            productKey={ProductKey.ENDPOINTS}
                            thingName="endpoint"
                            description={
                                activeTab === 'usage'
                                    ? ENDPOINTS_USAGE_PRODUCT_DESCRIPTION
                                    : ENDPOINTS_PRODUCT_DESCRIPTION
                            }
                            docsURL="https://posthog.com/docs/endpoints"
                            customHog={BigLeaguesHog}
                            isEmpty={false}
                            action={() =>
                                router.actions.push(
                                    urls.sqlEditor(undefined, undefined, undefined, undefined, OutputTab.Endpoint)
                                )
                            }
                        />
                        <LemonTabs activeKey={activeTab} data-attr="endpoints-tabs" tabs={tabs} sceneInset />
                    </SceneContent>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

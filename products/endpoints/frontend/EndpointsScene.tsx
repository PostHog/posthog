import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/types'

import { Endpoints } from './Endpoints'
import { EndpointsUsage } from './EndpointsUsage'
import { endpointsLogic } from './endpointsLogic'
import { endpointsUsageLogic } from './endpointsUsageLogic'

const ENDPOINTS_PRODUCT_DESCRIPTION =
    'Endpoints help you create pre-built SQL queries that you can easily use in your application via our API. Please note that endpoints is in alpha and may not be fully reliable or set in stone.'
const ENDPOINTS_API_USAGE_PRODUCT_DESCRIPTION =
    'Monitor your API usage and cost. Please note that endpoints is in alpha and may not be fully reliable. Things will change as we learn what you need.'

export const scene: SceneExport = {
    component: EndpointsScene,
    logic: endpointsUsageLogic,
}

export function EndpointsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { activeTab } = useValues(endpointsUsageLogic({ tabId: tabId || '' }))

    const tabs: LemonTab<string>[] = [
        {
            key: 'endpoints',
            label: 'Endpoints',
            content: <Endpoints tabId={tabId || ''} />,
            link: urls.endpoints(),
        },
        {
            key: 'usage',
            label: 'API usage',
            content: <EndpointsUsage tabId={tabId || ''} />,
            link: urls.endpointsUsage(),
        },
    ]
    return (
        <BindLogic logic={endpointsUsageLogic} props={{ key: 'endpointsUsageScene', tabId: tabId || '' }}>
            <BindLogic logic={endpointsLogic} props={{ key: 'endpointsLogic', tabId: tabId || '' }}>
                <SceneContent>
                    <SceneTitleSection
                        name={sceneConfigurations[Scene.EndpointsScene].name}
                        description={sceneConfigurations[Scene.EndpointsScene].description}
                        resourceType={{
                            type: sceneConfigurations[Scene.EndpointsScene].iconType || 'default_icon_type',
                        }}
                        actions={
                            <LemonButton
                                size="small"
                                data-attr="new-endpoint"
                                onClick={() => {
                                    router.actions.push(
                                        urls.sqlEditor(undefined, undefined, undefined, undefined, OutputTab.Endpoint)
                                    )
                                }}
                                type="primary"
                                tooltip="Redirects you to the SQL Editor."
                            >
                                New endpoint
                            </LemonButton>
                        }
                    />
                    <LemonBanner
                        type="warning"
                        dismissKey="endpoints-beta-banner"
                        action={{ children: 'Send feedback', id: 'endpoints-feedback-button' }}
                    >
                        <p>
                            Endpoints is in alpha and it may not be fully reliable. We are actively working on it and it
                            may change while we work with you on what works best. Please let us know what you'd like to
                            see here and/or report any issues directly to us!
                        </p>
                    </LemonBanner>
                    <SceneDivider />
                    <ProductIntroduction
                        productName="endpoints"
                        productKey={ProductKey.ENDPOINTS}
                        thingName="endpoint"
                        description={
                            activeTab === 'endpoints'
                                ? ENDPOINTS_PRODUCT_DESCRIPTION
                                : ENDPOINTS_API_USAGE_PRODUCT_DESCRIPTION
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
    )
}

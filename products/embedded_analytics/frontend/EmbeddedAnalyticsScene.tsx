import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/types'

import { QueryEndpoints } from './QueryEndpoints'
import { Usage } from './Usage'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'
import { queryEndpointsLogic } from './queryEndpointsLogic'

const EMBEDDED_ANALYTICS_QUERY_ENDPOINTS_PRODUCT_DESCRIPTION =
    'Embedded analytics help you create pre-built SQL queries that you can easily use in your application via our API. Please note that embedded analytics is in alpha and may not be fully reliable or set in stone.'
const EMBEDDED_ANALYTICS_API_USAGE_PRODUCT_DESCRIPTION =
    'Monitor your API usage and cost. Please note that embedded analytics is in alpha and may not be fully reliable or set in stone.'

export const scene: SceneExport = {
    component: EmbeddedAnalyticsScene,
    logic: embeddedAnalyticsLogic,
}

export function EmbeddedAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { activeTab } = useValues(embeddedAnalyticsLogic({ tabId: tabId || '' }))

    const tabs: LemonTab<string>[] = [
        {
            key: 'query-endpoints',
            label: 'Query endpoints',
            content: <QueryEndpoints tabId={tabId || ''} />,
            link: urls.embeddedAnalyticsQueryEndpoints(),
        },
        {
            key: 'usage',
            label: 'API usage',
            content: <Usage tabId={tabId || ''} />,
            link: urls.embeddedAnalyticsUsage(),
        },
    ]
    return (
        <BindLogic logic={embeddedAnalyticsLogic} props={{ key: 'embeddedAnalyticsScene', tabId: tabId || '' }}>
            <BindLogic logic={queryEndpointsLogic} props={{ key: 'queryEndpointsLogic', tabId: tabId || '' }}>
                <SceneContent>
                    <SceneTitleSection
                        name="Embedded analytics"
                        description="Define queries your application will use via the API and monitor their cost and usage."
                        resourceType={{
                            type: 'embedded_analytics',
                        }}
                        actions={
                            <LemonButton
                                size="small"
                                data-attr="new-query-endpoint"
                                onClick={() => {
                                    router.actions.push(
                                        urls.sqlEditor(
                                            undefined,
                                            undefined,
                                            undefined,
                                            undefined,
                                            OutputTab.QueryEndpoint
                                        )
                                    )
                                }}
                                type="primary"
                                tooltip="Redirects you to the SQL Editor."
                            >
                                New query endpoint
                            </LemonButton>
                        }
                    />
                    <LemonBanner
                        type="warning"
                        dismissKey="embedded-analytics-beta-banner"
                        action={{ children: 'Send feedback', id: 'embedded-analytics-feedback-button' }}
                    >
                        <p>
                            Embedded analytics is in alpha and it may not be fully reliable. We are actively working on
                            it and it may change while we work with you on what works best. Please let us know what
                            you'd like to see here and/or report any issues directly to us!
                        </p>
                    </LemonBanner>
                    <SceneDivider />
                    <ProductIntroduction
                        productName="embedded analytics"
                        productKey={ProductKey.EMBEDDED_ANALYTICS}
                        thingName="query endpoint"
                        description={
                            activeTab === 'query-endpoints'
                                ? EMBEDDED_ANALYTICS_QUERY_ENDPOINTS_PRODUCT_DESCRIPTION
                                : EMBEDDED_ANALYTICS_API_USAGE_PRODUCT_DESCRIPTION
                        }
                        docsURL="https://posthog.com/docs/embedded-analytics"
                        customHog={BigLeaguesHog}
                        isEmpty={false}
                        action={() =>
                            router.actions.push(
                                urls.sqlEditor(undefined, undefined, undefined, undefined, OutputTab.QueryEndpoint)
                            )
                        }
                    />
                    <LemonTabs activeKey={activeTab} data-attr="embedded-analytics-tabs" tabs={tabs} sceneInset />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}

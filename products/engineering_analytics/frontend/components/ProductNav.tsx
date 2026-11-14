import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { PRODUCT_TABS } from '../lib/productTabs'
import { withScope } from '../lib/scope'
import type { EngineeringAnalyticsView } from '../scenes/engineeringAnalyticsSceneLogic'

export interface ProductNavProps {
    /** A detail page passes the tab it drills down from. */
    activeTab: EngineeringAnalyticsView
    repo: string | null
    sourceId: string | null
    children: JSX.Element
}

export function ProductNav({ activeTab, repo, sourceId, children }: ProductNavProps): JSX.Element {
    const { searchParams } = useValues(router)

    return (
        <LemonTabs
            activeKey={activeTab}
            data-attr="engineering-analytics-tabs"
            sceneInset
            tabs={PRODUCT_TABS.map((tab) => ({
                key: tab.key,
                label: tab.label,
                link: withScope(tab.url(repo), searchParams, sourceId),
                'data-attr': tab.dataAttr,
                content: tab.key === activeTab ? children : <></>,
            }))}
        />
    )
}

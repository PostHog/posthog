import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { PRODUCT_TABS } from '../lib/productTabs'
import { withScope } from '../lib/scope'
import type { EngineeringAnalyticsView } from '../scenes/engineeringAnalyticsSceneLogic'

export interface ProductNavProps {
    /** The tab to highlight. A detail page passes the tab it drills down from. */
    activeTab: EngineeringAnalyticsView
    /** The 'owner/name' the page shows, so every tab opens in the same repository. */
    repo: string | null
    sourceId: string | null
    /** The active tab's content: a tab's own page, or the detail page beneath it. */
    children: JSX.Element
}

/** The product's tab bar, shared by the tab pages and every detail page under them. */
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

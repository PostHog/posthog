import { FeatureFlagKey, FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { TodayPaneProduct, isPaneProductShown, paneProductForPath } from '~/layout/today/todayPaneProducts'
import { FileSystemImport } from '~/queries/schema/schema-general'

interface TodayHomeRowSpec {
    // pinned: part of the row's `data-attr`.
    key: string
    label: string
    href: string
    /**
     * The navigation page the row borrows its icon, hover card and flag from. The Inbox tabs are not navigation
     * pages of their own, so their rows borrow the Inbox page and show only when the Products pane shows it.
     */
    navHref: string
    requiredFlags?: FeatureFlagKey[]
    section?: string
}

function homeTopSpecs(): TodayHomeRowSpec[] {
    return [
        { key: 'today', label: 'Today', href: urls.projectHomepage(), navHref: urls.projectRoot(), section: '/' },
        {
            key: 'inbox-reports',
            label: sceneConfigurations[Scene.Inbox].name ?? 'Self-driving inbox',
            href: urls.inbox('reports'),
            navHref: urls.inbox(),
        },
        {
            key: 'inbox-monitoring',
            label: 'Monitoring',
            href: urls.inbox('monitoring'),
            navHref: urls.inbox(),
            requiredFlags: [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING],
        },
        { key: 'pulse', label: 'Pulse', href: urls.pulse(), navHref: urls.pulse() },
    ]
}

function homeRows(pages: FileSystemImport[], specs: TodayHomeRowSpec[]): TodayPaneProduct[] {
    return specs.flatMap(({ key, label, href, navHref, section }) => {
        const item = pages.find((page) => page.href === navHref)
        return item ? [{ key, label, href, item, matchPaths: [href, ...(section ? [section] : [])] }] : []
    })
}

function shownHomeRows(
    pages: FileSystemImport[],
    specs: TodayHomeRowSpec[],
    featureFlags: FeatureFlagsSet
): TodayPaneProduct[] {
    const flagged = specs.filter((spec) => (spec.requiredFlags ?? []).every((flag) => !!featureFlags[flag]))
    return homeRows(pages, flagged).filter((product) => isPaneProductShown(product, featureFlags))
}

export function homeItems(featureFlags: FeatureFlagsSet): TodayPaneProduct[] {
    return shownHomeRows(getNavProductPages(), homeTopSpecs(), featureFlags)
}

export function homeProductForPath(path: string): TodayPaneProduct | undefined {
    return paneProductForPath(homeRows(getNavProductPages(), homeTopSpecs()), path)
}

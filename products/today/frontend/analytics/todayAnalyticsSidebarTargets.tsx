import {
    IconBell,
    IconBox,
    IconDashboard,
    IconDatabase,
    IconGraph,
    IconList,
    IconNotebook,
    IconNotification,
    IconPerson,
    IconPieChart,
    IconPlus,
} from '@posthog/icons'

import { urls } from 'scenes/urls'

import type { TodayExplainerPreview } from '~/layout/today/todayPreviewCards'
import { InsightShortId } from '~/types'

import type {
    AnalyticsDashboardTargetApi,
    FragmentIconApi,
    AnalyticsInsightTargetApi,
    AnalyticsNotebookTargetApi,
    AnalyticsPageApi,
    AnalyticsPageTargetApi,
} from 'products/ui_customization/frontend/generated/api.schemas'
import { SIDEBAR_ICONS } from 'products/ui_customization/frontend/sidebarIcons'

export type SidebarTarget =
    | AnalyticsPageTargetApi
    | AnalyticsInsightTargetApi
    | AnalyticsDashboardTargetApi
    | AnalyticsNotebookTargetApi

export interface ResolvedSidebarTarget {
    label: string
    icon: JSX.Element
    to: string
    /** The path that marks the target as open. */
    path: string
    explainer?: TodayExplainerPreview
}

function sidebarPage(
    label: string,
    icon: JSX.Element,
    to: string,
    explainer?: Omit<TodayExplainerPreview, 'kind' | 'label' | 'icon'>,
    path: string = to
): ResolvedSidebarTarget {
    return { label, icon, to, path, explainer: explainer && { kind: 'explainer', label, icon, ...explainer } }
}

// Module constants, so the shared hover card gets the same payload on every render.
export const SIDEBAR_PAGES: Record<AnalyticsPageApi, ResolvedSidebarTarget> = {
    analytics_all: sidebarPage('View all', <IconList />, urls.analyticsList(), {
        description:
            'Browse every canvas, dashboard, notebook, and insight your project shares. Filter by type, creator, or collection.',
        example: 'Find the retention dashboard a teammate made last month.',
    }),
    analytics_mine: sidebarPage('My work', <IconPerson />, urls.analyticsMine(), {
        description: 'See everything you created, including work you have not shared with your project yet.',
        example: 'Pick up a draft insight you started yesterday.',
    }),
    collections: sidebarPage('Collections', <IconBox />, urls.analyticsSpaces(), {
        description:
            'Keep related analytics together where your team can find it. Pin a collection to show it in this sidebar.',
        example: 'Keep all the growth team’s dashboards and insights in one collection.',
    }),
    alerts: sidebarPage('Alerts', <IconBell />, urls.alerts(), {
        description: 'Watch the metrics in your insights and get a notification when a value crosses a threshold.',
        example: 'Get an email when daily signups drop below 100.',
        docsHref: 'https://posthog.com/docs/alerts',
    }),
    subscriptions: sidebarPage(
        'Subscriptions',
        <IconNotification />,
        `${urls.subscriptions()}?tab=mine`,
        {
            description:
                'Get insights and dashboards delivered on a schedule by email or Slack. Manage the subscriptions you have set up.',
            example: 'Send the weekly activation dashboard to your team every Monday.',
        },
        urls.subscriptions()
    ),
    product_analytics: sidebarPage('Product analytics', <IconGraph />, urls.analyticsProductHome()),
    web_analytics: sidebarPage('Web analytics', <IconPieChart />, urls.webAnalytics()),
    sql_editor: sidebarPage('SQL editor', <IconDatabase />, urls.sqlEditor()),
    new_insight: sidebarPage('New insight', <IconPlus />, urls.insightNew()),
}

/** Where a layout item leads, or null for a page this version of the app does not know. */
export function resolveSidebarTarget(
    target: SidebarTarget,
    label?: string | null,
    icon?: FragmentIconApi | null
): ResolvedSidebarTarget | null {
    const chosenIcon = icon ? SIDEBAR_ICONS[icon] : undefined
    switch (target.kind) {
        case 'page': {
            const page = SIDEBAR_PAGES[target.page] as ResolvedSidebarTarget | undefined
            return page ? { ...page, label: label ?? page.label, icon: chosenIcon ?? page.icon } : null
        }
        case 'insight':
            return objectTarget(urls.insightView(target.short_id as InsightShortId), label, chosenIcon ?? <IconGraph />)
        case 'dashboard':
            return objectTarget(urls.dashboard(target.id), label, chosenIcon ?? <IconDashboard />)
        case 'notebook':
            return objectTarget(urls.notebook(target.short_id), label, chosenIcon ?? <IconNotebook />)
        default:
            return null
    }
}

function objectTarget(to: string, label: string | null | undefined, icon: JSX.Element): ResolvedSidebarTarget | null {
    return label ? { label, icon, to, path: to } : null
}

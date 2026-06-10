import { JSX, useMemo } from 'react'

import {
    IconDashboard,
    IconDatabase,
    IconGraph,
    IconHogQL,
    IconLive,
    IconLlmAnalytics,
    IconLogomark,
    IconMessage,
    IconPieChart,
    IconPlug,
    IconRewindPlay,
    IconTestTube,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import type { AcpMessage } from './acp-types'
import { accumulateSessionResources } from './contextUsage'

/** Icon per PostHog product id, mirroring the desktop app's PRODUCT_ICON map. */
const PRODUCT_ICON: Record<string, JSX.Element> = {
    product_analytics: <IconGraph />,
    web_analytics: <IconPieChart />,
    feature_flags: <IconToggle />,
    experiments: <IconTestTube />,
    error_tracking: <IconWarning />,
    session_replay: <IconRewindPlay />,
    surveys: <IconMessage />,
    llm_analytics: <IconLlmAnalytics />,
    data_warehouse: <IconDatabase />,
    cdp: <IconPlug />,
    logs: <IconLive />,
    apm: <IconDashboard />,
    sql: <IconHogQL />,
    posthog: <IconLogomark />,
}

/**
 * Docs page on posthog.com per product. Partial on purpose — products without
 * a dedicated docs page render as a plain, non-clickable tag rather than
 * linking somewhere misleading.
 */
const PRODUCT_DOC_URL: Record<string, string> = {
    product_analytics: 'https://posthog.com/docs/product-analytics',
    web_analytics: 'https://posthog.com/docs/web-analytics',
    feature_flags: 'https://posthog.com/docs/feature-flags',
    experiments: 'https://posthog.com/docs/experiments',
    error_tracking: 'https://posthog.com/docs/error-tracking',
    session_replay: 'https://posthog.com/docs/session-replay',
    surveys: 'https://posthog.com/docs/surveys',
    llm_analytics: 'https://posthog.com/docs/ai-observability',
    data_warehouse: 'https://posthog.com/docs/data-warehouse',
    cdp: 'https://posthog.com/docs/cdp',
    logs: 'https://posthog.com/docs/logs',
    sql: 'https://posthog.com/docs/sql',
    posthog: 'https://posthog.com/docs',
}

interface SessionResourcesBarProps {
    events: AcpMessage[]
}

/**
 * Persistent bar above the composer listing the PostHog products the agent has
 * touched so far this session. Each product appears once, added the moment it
 * is first used. Hidden until at least one product has been used.
 */
export function SessionResourcesBar({ events }: SessionResourcesBarProps): JSX.Element | null {
    const products = useMemo(() => accumulateSessionResources(events), [events])

    if (products.length === 0) {
        return null
    }

    return (
        <div className="flex items-center flex-wrap gap-2 mb-2">
            <span className="whitespace-nowrap text-xs text-muted">PostHog resources used</span>
            {products.map((product) => {
                const icon = PRODUCT_ICON[product.id] ?? <IconLogomark />
                const docUrl = PRODUCT_DOC_URL[product.id]
                const tag = (
                    <LemonTag icon={icon} className={docUrl ? 'cursor-pointer hover:bg-fill-highlight-100' : undefined}>
                        {product.label}
                    </LemonTag>
                )
                if (!docUrl) {
                    return <span key={product.id}>{tag}</span>
                }
                return (
                    <Link
                        key={product.id}
                        to={docUrl}
                        target="_blank"
                        title={`Open ${product.label} docs`}
                        className="no-underline"
                    >
                        {tag}
                    </Link>
                )
            })}
        </div>
    )
}

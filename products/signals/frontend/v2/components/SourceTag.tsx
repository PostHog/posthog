import { IconCursorClick, IconGithub } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

/** Sources that map onto a PostHog product reuse that product's icon and color. */
const PRODUCT_ICON_TYPES: Record<string, FileSystemIconType> = {
    'Product analytics': 'product_analytics',
    'Session replay': 'session_replay',
    'Error tracking': 'error_tracking',
    'Feature flags': 'feature_flag',
    'Web vitals': 'web_analytics',
    'Support tickets': 'conversations',
    Logs: 'logs',
    Surveys: 'survey',
}

const OTHER_ICONS: Record<string, JSX.Element> = {
    Autocapture: <IconCursorClick />,
    GitHub: <IconGithub />,
}

function iconForSource(source: string): JSX.Element | undefined {
    const productType = PRODUCT_ICON_TYPES[source]
    return productType ? iconForType(productType) : OTHER_ICONS[source]
}

/** A signal source chip. The fill keeps it from blending into the row behind it. */
export function SourceTag({ source }: { source: string }): JSX.Element {
    return (
        <LemonTag size="small" type="none" icon={iconForSource(source)} className="bg-surface-tertiary text-secondary">
            {source}
        </LemonTag>
    )
}

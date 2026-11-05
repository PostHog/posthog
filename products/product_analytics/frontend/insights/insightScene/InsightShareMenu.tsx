import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconShare } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

interface InsightShareMenuProps {
    insight: { short_id?: string | null; name?: string | null; derived_name?: string | null }
}

export interface InsightShareItem {
    label: string
    onClick: () => void
    dataAttr: string
}

/** The share options of a saved insight, or null when it has no short id yet. */
export function useInsightShareItems(insight: InsightShareMenuProps['insight']): InsightShareItem[] | null {
    const { push } = useActions(router)
    const shortId = insight.short_id
    if (!shortId) {
        return null
    }
    return [
        {
            label: 'Share publicly or embed',
            onClick: () => push(urls.insightSharing(shortId as InsightShortId)),
            dataAttr: 'insight-share-publicly',
        },
    ]
}

/** The Share menu of a saved insight under the Today navigation. */
export function InsightShareMenu({ insight }: InsightShareMenuProps): JSX.Element | null {
    const shareItems = useInsightShareItems(insight)
    if (!shareItems) {
        return null
    }
    return (
        <LemonMenu
            items={shareItems.map(({ label, onClick, dataAttr }) => ({
                label,
                onClick,
                'data-attr': dataAttr,
            }))}
        >
            <LemonButton type="secondary" size="small" icon={<IconShare />} data-attr="insight-share-menu">
                Share
            </LemonButton>
        </LemonMenu>
    )
}

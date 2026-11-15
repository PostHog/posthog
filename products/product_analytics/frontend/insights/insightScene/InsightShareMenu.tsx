import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconGlobe, IconShare } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

interface InsightShareMenuProps {
    insight: { short_id?: string | null; name?: string | null; derived_name?: string | null }
}

export interface InsightShareItem {
    label: string
    icon?: JSX.Element
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
            icon: <IconGlobe />,
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
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" data-attr="insight-share-menu" />}>
                <IconShare />
                Share
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {shareItems.map(({ label, icon, onClick, dataAttr }) => (
                    <DropdownMenuItem key={dataAttr} onClick={onClick} data-attr={dataAttr}>
                        {icon}
                        {label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

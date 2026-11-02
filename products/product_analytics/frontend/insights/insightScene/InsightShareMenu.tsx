import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconShare } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { analyticsShareLogic, shareTargetKey } from 'scenes/analytics/analyticsShareLogic'
import { ShareToSpaceModal } from 'scenes/analytics/ShareToSpaceModal'
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
    const { openShareToSpace } = useActions(analyticsShareLogic)
    const { itemSpaces } = useValues(analyticsShareLogic)
    const shortId = insight.short_id
    if (!shortId) {
        return null
    }
    const insightName = insight.name || insight.derived_name || 'Untitled insight'
    const insightSpace = itemSpaces[shareTargetKey({ type: 'insight', ref: shortId })]
    return [
        {
            label: insightSpace ? `Move from ${insightSpace}` : 'Add to a collection',
            icon: <IconShare />,
            onClick: () => openShareToSpace({ type: 'insight', ref: shortId, name: insightName }),
            dataAttr: 'insight-share-into-space',
        },
        {
            label: 'Share publicly or embed',
            onClick: () => push(urls.insightSharing(shortId as InsightShortId)),
            dataAttr: 'insight-share-publicly',
        },
    ]
}

/**
 * The Share menu of a saved insight under the Today navigation. It lives apart from the header so the
 * spaces logics, and the project tree they load, mount only for people with the flag.
 */
export function InsightShareMenu({ insight }: InsightShareMenuProps): JSX.Element | null {
    const { loadItemSpace } = useActions(analyticsShareLogic)
    const { itemSpaces } = useValues(analyticsShareLogic)
    const shareItems = useInsightShareItems(insight)
    const shortId = insight.short_id
    const insightName = insight.name || insight.derived_name || 'Untitled insight'
    const insightSpace = shortId ? itemSpaces[shareTargetKey({ type: 'insight', ref: shortId })] : undefined

    useEffect(() => {
        if (shortId && insightSpace === undefined) {
            loadItemSpace({ type: 'insight', ref: shortId, name: insightName })
        }
    }, [shortId, insightSpace, insightName, loadItemSpace])

    if (!shareItems) {
        return null
    }
    return (
        <>
            <LemonMenu
                items={shareItems.map(({ label, icon, onClick, dataAttr }) => ({
                    label,
                    icon,
                    onClick,
                    'data-attr': dataAttr,
                }))}
            >
                <LemonButton type="secondary" size="small" icon={<IconShare />} data-attr="insight-share-menu">
                    Share
                </LemonButton>
            </LemonMenu>
            <ShareToSpaceModal />
        </>
    )
}

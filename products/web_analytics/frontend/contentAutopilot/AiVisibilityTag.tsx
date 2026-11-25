import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { quillBadgeVariant } from 'lib/lemon-ui/LemonTag/quillBadgeVariant'

export interface AiVisibilityTagProps {
    type?: LemonTagType
    size?: 'small' | 'medium'
    className?: string
    title?: string
    'data-attr'?: string
    children: React.ReactNode
}

/** A tag in AI visibility: a quill badge under the new navigation, a Lemon tag otherwise. */
export const AiVisibilityTag = ({
    type,
    size,
    className,
    title,
    'data-attr': dataAttr,
    children,
}: AiVisibilityTagProps): JSX.Element => {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Badge variant={quillBadgeVariant(type)} className={className} title={title} data-attr={dataAttr}>
                {children}
            </Badge>
        )
    }
    return (
        <LemonTag type={type} size={size} className={className} title={title} data-attr={dataAttr}>
            {children}
        </LemonTag>
    )
}

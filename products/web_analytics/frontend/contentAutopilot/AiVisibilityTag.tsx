import { Badge } from '@posthog/quill'

import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { quillBadgeVariant } from 'lib/lemon-ui/LemonTag/quillBadgeVariant'

export interface AiVisibilityTagProps {
    type?: LemonTagType
    className?: string
    title?: string
    'data-attr'?: string
    children: React.ReactNode
}

export const AiVisibilityTag = ({
    type,
    className,
    title,
    'data-attr': dataAttr,
    children,
}: AiVisibilityTagProps): JSX.Element => (
    <Badge variant={quillBadgeVariant(type)} className={className} title={title} data-attr={dataAttr}>
        {children}
    </Badge>
)

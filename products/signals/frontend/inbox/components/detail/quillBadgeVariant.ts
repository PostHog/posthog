import type { LemonTagType } from '@posthog/lemon-ui'

export type QuillBadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

const VARIANT_BY_TAG_TYPE: Record<LemonTagType, QuillBadgeVariant> = {
    primary: 'info',
    option: 'info',
    highlight: 'info',
    info: 'info',
    warning: 'warning',
    caution: 'warning',
    danger: 'destructive',
    success: 'success',
    completion: 'completed',
    default: 'default',
    muted: 'default',
    none: 'default',
}

/** The quill `Badge` variant for a tag type that the shared presentation helpers hand to `LemonTag`. */
export function quillBadgeVariant(type: LemonTagType | undefined): QuillBadgeVariant {
    return type ? VARIANT_BY_TAG_TYPE[type] : 'default'
}

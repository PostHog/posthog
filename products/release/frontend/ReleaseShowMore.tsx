import { Button } from '@posthog/quill'

export const SHOW_MORE_PAGE = 20

export function ReleaseShowMore({
    total,
    visible,
    limit,
    onChange,
    dataAttr,
}: {
    total: number
    visible: number
    limit: number
    onChange: (visible: number) => void
    dataAttr: string
}): JSX.Element | null {
    const remaining = total - Math.min(visible, total)
    if (total <= limit) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-2">
            {remaining > 0 && (
                <Button
                    variant="link-muted"
                    size="sm"
                    onClick={() => onChange(visible + SHOW_MORE_PAGE)}
                    data-attr={`${dataAttr}-show-more`}
                >
                    {`Show ${Math.min(remaining, SHOW_MORE_PAGE)} more of ${remaining}`}
                </Button>
            )}
            {visible > limit && (
                <Button
                    variant="link-muted"
                    size="sm"
                    onClick={() => onChange(limit)}
                    data-attr={`${dataAttr}-show-less`}
                >
                    Show less
                </Button>
            )}
        </div>
    )
}

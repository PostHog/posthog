import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

export interface PageStatCardProps {
    label: string
    aside?: React.ReactNode
    value: React.ReactNode
    detail: React.ReactNode
    loading: boolean
    tooltip?: React.ReactNode
    /** Without it the card is a plain, non-interactive cell. */
    onClick?: () => void
    onHover?: () => void
    'data-attr': string
}

export function PageStatCard({
    label,
    aside,
    value,
    detail,
    loading,
    tooltip,
    onClick,
    onHover,
    'data-attr': dataAttr,
}: PageStatCardProps): JSX.Element {
    const body = (
        <>
            <span className="flex items-center justify-between gap-2 min-w-0 text-sm">
                <span className="text-secondary truncate">{label}</span>
                {loading ? null : aside}
            </span>
            {loading ? (
                <>
                    <LemonSkeleton className="h-7 w-20 my-0.5" />
                    <LemonSkeleton className="h-3 w-32" />
                </>
            ) : (
                <>
                    <span className="text-xl leading-8 font-semibold tabular-nums truncate" translate="no">
                        {value}
                    </span>
                    <span className="text-xs text-secondary truncate">{detail}</span>
                </>
            )}
        </>
    )
    const card = onClick ? (
        <button
            type="button"
            className="text-left px-4 py-3 flex flex-col gap-0.5 min-w-0 cursor-pointer hover:bg-fill-highlight-50 focus-visible:outline-2 focus-visible:-outline-offset-2 transition-colors motion-reduce:transition-none"
            onClick={onClick}
            onMouseEnter={onHover}
            aria-busy={loading}
            data-attr={dataAttr}
        >
            {body}
        </button>
    ) : (
        <div className="px-4 py-3 flex flex-col gap-0.5 min-w-0" aria-busy={loading} data-attr={dataAttr}>
            {body}
        </div>
    )
    return tooltip ? (
        <Tooltip title={tooltip} placement="bottom">
            {card}
        </Tooltip>
    ) : (
        card
    )
}

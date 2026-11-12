import { IconExternal } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

/** Render inside a `w-full max-w-0` column, so a long nodeid truncates instead of widening the table. */
export function TestIdCell({
    nodeid,
    url,
    tooltip,
}: {
    nodeid: string
    url: string | null
    tooltip: string
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            {url ? (
                <Link
                    to={url}
                    target="_blank"
                    targetBlankIcon={false}
                    className="flex max-w-full items-center gap-1 font-mono text-xs"
                >
                    {/* The icon leads so truncating a long nodeid never clips it away. */}
                    <IconExternal className="shrink-0" />
                    <span className="truncate">{nodeid}</span>
                </Link>
            ) : (
                <span className="block max-w-full truncate font-mono text-xs">{nodeid}</span>
            )}
        </Tooltip>
    )
}

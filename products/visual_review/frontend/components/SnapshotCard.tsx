import { IconWarning } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import type { BaselineEntryApi } from '../generated/api.schemas'
import { parseArea, parseTheme } from '../lib/parseIdentifier'
import { InlineSparkline } from './InlineSparkline'

export function SnapshotCard({
    repoId,
    entry,
    thumbnailBasePath,
}: {
    repoId: string
    entry: BaselineEntryApi
    thumbnailBasePath: string | null
}): JSX.Element {
    const { theme } = parseTheme(entry.identifier)
    const area = parseArea(entry.identifier)
    const tolerateCount = entry.tolerate_count_30d
    // Only build the thumbnail URL when we know there's a thumbnail to fetch —
    // otherwise the endpoint 404s and browsers show the broken-image glyph.
    const thumbnailUrl =
        thumbnailBasePath && entry.thumbnail_hash
            ? `${thumbnailBasePath}/${encodeURIComponent(entry.identifier)}/`
            : null
    const href = urls.visualReviewSnapshotHistory(repoId, entry.run_type, entry.identifier)

    return (
        <Link
            to={href}
            // Without an explicit border-color, Tailwind's `border` falls back
            // to `currentColor` — and Link sets `currentColor` to the primary
            // orange. That painted every card with an orange frame.
            className="border border-border rounded bg-bg-light overflow-hidden flex flex-col text-default hover:border-primary transition-colors"
            data-attr="visual-review-snapshot-card"
        >
            <div
                // Thumbnails are bounded by pixelhog at THUMB_WIDTH (200) ×
                // THUMB_HEIGHT (140), so we know the box can never overflow.
                // Fix the height to the cap and align top so taller content
                // anchors consistently across cards; shorter content lets
                // the bg-light (or bg-3000 for dark variants) show beneath.
                className={`relative h-[140px] flex items-start justify-center overflow-hidden border-b border-border ${
                    theme === 'dark' ? 'bg-bg-3000' : 'bg-bg-light'
                }`}
            >
                {thumbnailUrl ? (
                    <img
                        src={thumbnailUrl}
                        alt={entry.identifier}
                        loading="lazy"
                        decoding="async"
                        className="max-w-full max-h-full object-contain"
                    />
                ) : (
                    <span className="text-muted text-xs my-auto">No thumbnail</span>
                )}
                <div className="absolute top-1.5 right-1.5 flex items-center gap-1">
                    {entry.is_quarantined && (
                        <Tooltip title="Currently quarantined — excluded from gating">
                            <span className="bg-warning text-white rounded-full w-5 h-5 flex items-center justify-center">
                                <IconWarning className="w-3 h-3" />
                            </span>
                        </Tooltip>
                    )}
                    {tolerateCount > 0 && (
                        <Tooltip title={`${tolerateCount} tolerate${tolerateCount === 1 ? '' : 's'} in last 30 days`}>
                            <span className="bg-primary-3000 text-white text-[10px] font-semibold rounded-full px-1.5 h-5 flex items-center">
                                ~{tolerateCount}
                            </span>
                        </Tooltip>
                    )}
                </div>
            </div>

            <div className="p-2 flex flex-col gap-1 min-w-0">
                <div className="font-mono text-xs truncate" title={entry.identifier}>
                    {entry.identifier}
                </div>
                <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
                    <LemonTag type="default" size="small">
                        {area}
                    </LemonTag>
                    <InlineSparkline data={entry.sparkline} className="h-4 w-16 shrink-0" />
                </div>
            </div>
        </Link>
    )
}

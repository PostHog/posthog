import { IconPerson, IconPlay } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { TaskSegmentLink } from '../types'

export interface TaskSegmentListProps {
    segments: TaskSegmentLink[]
    loading: boolean
    hasMore: boolean
    onSegmentClick: (segment: TaskSegmentLink) => void
    onLoadMore: () => void
}

function SegmentItem({ segment, onClick }: { segment: TaskSegmentLink; onClick: () => void }): JSX.Element {
    const timestamp = segment.segment_timestamp ? dayjs(segment.segment_timestamp) : null

    return (
        <button
            onClick={onClick}
            className="w-full text-left px-4 py-3 border border-border rounded hover:bg-bg-light transition-colors group"
        >
            <div className="flex items-start gap-3">
                <div className="flex-shrink-0 mt-0.5 text-muted group-hover:text-primary transition-colors">
                    <IconPlay className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                    <p className="text-sm mb-1 line-clamp-2">{segment.content || 'No description available'}</p>
                    <div className="flex items-center gap-3 text-xs text-muted">
                        <span className="flex items-center gap-1">
                            <IconPerson className="w-3 h-3" />
                            <span className="font-mono truncate max-w-[120px]" title={segment.distinct_id}>
                                {segment.distinct_id}
                            </span>
                        </span>
                        {timestamp && <span>{timestamp.format('MMM D, HH:mm')}</span>}
                        <span className="font-mono">
                            {segment.segment_start_time} - {segment.segment_end_time}
                        </span>
                    </div>
                </div>
            </div>
        </button>
    )
}

export function TaskSegmentList({
    segments,
    loading,
    hasMore,
    onSegmentClick,
    onLoadMore,
}: TaskSegmentListProps): JSX.Element {
    if (loading && segments.length === 0) {
        return (
            <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                    <div key={i} className="px-4 py-3 border border-border rounded">
                        <LemonSkeleton className="h-4 w-3/4 mb-2" />
                        <LemonSkeleton className="h-3 w-1/2" />
                    </div>
                ))}
            </div>
        )
    }

    if (segments.length === 0) {
        return <div className="text-center py-8 text-muted">No video segments linked to this task</div>
    }

    return (
        <div className="space-y-2">
            {segments.map((segment) => (
                <SegmentItem key={segment.id} segment={segment} onClick={() => onSegmentClick(segment)} />
            ))}
            {hasMore && (
                <div className="pt-2">
                    <LemonButton type="secondary" size="small" onClick={onLoadMore} loading={loading} fullWidth center>
                        Show more segments
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

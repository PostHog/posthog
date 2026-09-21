import { SEGMENT_KIND_STYLES, SEGMENT_LEGEND_GROUPS, segmentBackground } from '../lib/pullRequestTimeline'

export function PullRequestTimelineLegend(): JSX.Element {
    return (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-secondary">
            {SEGMENT_LEGEND_GROUPS.map((group) => (
                <span key={group.label} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-tertiary">{group.label}</span>
                    {group.kinds.map((kind) => (
                        <span key={kind} className="flex items-center gap-1">
                            <span className="h-2.5 w-3 rounded-sm" style={segmentBackground(kind)} />
                            {SEGMENT_KIND_STYLES[kind].short}
                        </span>
                    ))}
                </span>
            ))}
        </div>
    )
}

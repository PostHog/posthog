// No repo figure: the cause comes from replaying each pull request's timeline, which is too heavy to run
// over the whole repository per request.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { compactAgeLabel } from '../lib/format'
import { RedTimeByCause } from '../lib/pullRequestDayView'
import { SEGMENT_KIND_STYLES, segmentBackground } from '../lib/pullRequestTimeline'

export function RedTimeByCauseCard({
    redTime,
    loading,
    jobsAvailable,
}: {
    redTime: RedTimeByCause
    loading: boolean
    jobsAvailable: boolean
}): JSX.Element {
    const total = redTime.totalSecondsPerMergedPr

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col p-4"
            data-attr="engineering-analytics-delivery-red-time"
        >
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip
                    title={
                        <div className="flex flex-col gap-1">
                            <div>
                                Time a merged pull request's latest commit had a failed check, per merged pull request,
                                split by what turned it green.
                            </div>
                            <div>
                                Flake: the failed workflow passed a re-run of the same commit. Master broken: the failed
                                jobs also failed on the default branch within 12 hours. Fixed by a push: a later commit
                                arrived. Not provable: none of those.
                            </div>
                            <div>
                                There is no repo figure: the cause comes from replaying each pull request, which only
                                runs for the pull requests listed here.
                            </div>
                            {!jobsAvailable && (
                                <div>
                                    The workflow jobs table isn't synced, so flakes and master breakage can't be seen.
                                </div>
                            )}
                        </div>
                    }
                >
                    <span className="cursor-default">Red checks, by what turned them green</span>
                </Tooltip>
            </h3>
            {loading ? (
                <LemonSkeleton className="h-16 w-full" />
            ) : redTime.mergedCount === 0 ? (
                <div className="flex h-16 items-center text-xs text-secondary">
                    No merged pull requests in the window.
                </div>
            ) : (
                <>
                    <div className="mb-3 flex flex-wrap items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {total > 0 ? compactAgeLabel(total) : '0m'}
                        </span>
                        <span className="text-xs tabular-nums text-tertiary">
                            red per merged pull request, over {pluralize(redTime.mergedCount, 'merged pull request')}
                        </span>
                    </div>
                    {total > 0 && (
                        <div className="flex h-2.5 gap-px overflow-hidden rounded-sm">
                            {redTime.secondsPerMergedPr
                                .filter((entry) => entry.seconds > 0)
                                .map((entry) => (
                                    <Tooltip
                                        key={entry.kind}
                                        title={`${SEGMENT_KIND_STYLES[entry.kind].label}: ${compactAgeLabel(entry.seconds)} per merged pull request`}
                                    >
                                        <div
                                            className="h-full"
                                            style={{ flex: `${entry.seconds} 1 0`, ...segmentBackground(entry.kind) }}
                                        />
                                    </Tooltip>
                                ))}
                        </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-secondary">
                        {redTime.secondsPerMergedPr.map((entry) => (
                            <span key={entry.kind} className="flex items-center gap-1 tabular-nums">
                                <span className="size-2.5 rounded-sm" style={segmentBackground(entry.kind)} />
                                {SEGMENT_KIND_STYLES[entry.kind].short} {compactAgeLabel(entry.seconds || null)}
                            </span>
                        ))}
                    </div>
                </>
            )}
        </LemonCard>
    )
}

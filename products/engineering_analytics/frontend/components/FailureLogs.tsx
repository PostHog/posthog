// CI failure log excerpts grouped by failed job. Lines come pre-thinned from the backend; omission
// markers (original_line == null) render muted so the elision is visible, never silent.

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { CIJobFailureLogApi } from '../generated/api.schemas'
import { CIAnalyticsLoadError } from './CIAnalyticsLoadError'

function JobFailureLog({ job, jobName }: { job: CIJobFailureLogApi; jobName?: string }): JSX.Element {
    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex items-center gap-2 border-b border-primary px-3 py-2 text-xs font-semibold">
                <LemonTag type="danger" size="small">
                    {job.conclusion === 'timed_out' ? 'Timed out' : 'Failed'}
                </LemonTag>
                <span className="truncate font-mono">{jobName ?? `job ${job.job_id}`}</span>
                {job.branch && <span className="font-mono font-normal text-tertiary">· {job.branch}</span>}
                <span className="ml-auto font-normal text-tertiary">
                    {job.line_count} of {job.original_total_lines || '?'} lines
                    {job.truncated ? ' · truncated' : ''}
                </span>
            </div>
            <table className="w-full border-collapse">
                <tbody>
                    {job.lines.map((line, i) => (
                        <tr key={i} className={cn(i > 0 && 'border-t border-primary')}>
                            <td className="w-14 px-3 py-1 align-top text-right font-mono text-[11px] tabular-nums text-tertiary whitespace-nowrap">
                                {line.original_line ?? '⋯'}
                            </td>
                            <td
                                className={cn(
                                    'px-3 py-1 align-top font-mono text-[11.5px] leading-relaxed break-all',
                                    line.original_line == null && 'italic text-tertiary'
                                )}
                            >
                                {line.text}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

/**
 * A set of failed jobs with their log excerpts, straight from the loader's union: ``null`` is the
 * not-loaded state, ``'unavailable'`` a failed fetch, and ``logs_available === false`` means the run
 * didn't fail or its logs aged out of retention.
 */
export function FailureLogGroups({
    logs,
    loading,
    onRetry,
    jobNames,
    errorDescription = 'Retry, or open the run on GitHub to read its logs.',
    emptyText = 'No failure logs. Nothing failed, or the logs have aged out of retention.',
}: {
    logs: { jobs: CIJobFailureLogApi[]; logs_available: boolean } | 'unavailable' | null | undefined
    loading: boolean
    onRetry: () => void
    /** job_id → display name, when the caller has the run's jobs loaded, because logs only carry ids. */
    jobNames?: Record<number, string>
    errorDescription?: string
    emptyText?: string
}): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="h-24 w-full" />
    }
    if (logs === 'unavailable') {
        return (
            <CIAnalyticsLoadError title="Couldn't load failure logs" description={errorDescription} onRetry={onRetry} />
        )
    }
    if (logs == null || !logs.logs_available || logs.jobs.length === 0) {
        return <div className="px-1 py-2 text-xs text-secondary">{emptyText}</div>
    }
    return (
        <div className="flex flex-col gap-2">
            {logs.jobs.map((job) => (
                <JobFailureLog key={`${job.run_id}:${job.job_id}`} job={job} jobName={jobNames?.[job.job_id]} />
            ))}
        </div>
    )
}

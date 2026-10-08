import { LemonBanner, LemonCollapse, LemonDrawer, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ScoutTrialResultApi, TrialComparisonReportApi } from 'products/signals/frontend/generated/api.schemas'

import { formatRunCost, formatRunDuration } from '../../../../utils/scoutRunsWindow'
import { ScoutTrialJudgment } from './ScoutTrialJudgment'
import { trialPromptLabel } from './scoutTrialPresentation'
import { trialReportText } from './scoutTrialUtils'

export function ScoutTrialRunDrawer({
    result,
    report,
    launchId,
    error,
    onClose,
}: {
    result: ScoutTrialResultApi | null
    report?: TrialComparisonReportApi | null
    launchId?: string | null
    error?: string | null
    onClose: () => void
}): JSX.Element | null {
    const selectedLaunchId = launchId ?? result?.launch_id
    if (!selectedLaunchId) {
        return null
    }
    const memory = Object.entries(result?.memory ?? {})
    const judgment = report?.runs.find((run) => run.launch_id === selectedLaunchId)
    const evidence = report?.evidence.find((run) => run.launch_id === selectedLaunchId)
    const version = report?.variants.find((variant) => variant.variant_id === judgment?.variant_id)
    const versionRuns = report?.runs.filter((run) => run.variant_id === judgment?.variant_id) ?? []
    const runIndex = versionRuns.findIndex((run) => run.launch_id === selectedLaunchId)
    const title = version ? `${version.label} · Run ${runIndex + 1} of ${version.total_runs}` : 'Run details'
    const model = result?.model ?? evidence?.model
    const effort = result?.reasoning_effort ?? evidence?.reasoning_effort
    const prompt = version?.is_baseline
        ? 'Baseline prompt'
        : evidence && report
          ? trialPromptLabel(
                [evidence],
                report.evidence.filter((run) => run.variant_id === report.baseline_variant_id)
            )
          : null
    const duration =
        result?.started_at && result.completed_at
            ? dayjs(result.completed_at).diff(dayjs(result.started_at), 'seconds', true)
            : null

    return (
        <LemonDrawer
            isOpen
            onClose={onClose}
            title={title}
            description={model ? [model, effort, prompt].filter(Boolean).join(' · ') : undefined}
            width={580}
            className="ph-no-capture ph-replay-block"
        >
            <div className="@container flex flex-col gap-4 min-w-0 break-words">
                {error && <LemonBanner type="warning">{error}</LemonBanner>}
                {!result && !judgment && !error && <LemonSkeleton className="h-32" />}
                {result?.status === 'failed' && !result.error && !result.invalid_reason && (
                    <LemonBanner type="error">This run failed. It was not judged.</LemonBanner>
                )}
                {result?.status === 'cancelled' && !result.error && !result.invalid_reason && (
                    <LemonBanner type="warning">This run was stopped. It was not judged.</LemonBanner>
                )}
                {(result?.error || result?.invalid_reason) && (
                    <LemonBanner type="error">{result.error || result.invalid_reason}</LemonBanner>
                )}
                {result?.export_error && (
                    <LemonBanner type="warning">
                        The saved export needs a retry. These inline results are still available to download.
                    </LemonBanner>
                )}
                {judgment && report && (
                    <div className="flex flex-col gap-3">
                        <ScoutTrialJudgment
                            judgment={judgment}
                            evidence={evidence}
                            criteria={report.criteria}
                            summary={result?.summary}
                        />
                    </div>
                )}
                <LemonCollapse
                    multiple
                    panels={[
                        !!result &&
                            !judgment && {
                                key: 'summary',
                                header: 'Run summary',
                                content: (
                                    <LemonMarkdown disableImages="all">
                                        {result.summary || 'The scout has not written a summary yet.'}
                                    </LemonMarkdown>
                                ),
                            },
                        !!result && {
                            key: 'reports',
                            header: `Captured reports (${result.reports.length})`,
                            content: result.reports.length ? (
                                <div className="flex flex-col gap-4">
                                    {result.reports.map((report) => (
                                        <div key={report.id} className="border-b last:border-b-0 pb-3">
                                            <LemonTag type="muted" className="mb-2">
                                                {report.source_report_id ? 'Updated existing report' : 'New report'}
                                            </LemonTag>
                                            <h4 className="break-words">
                                                {typeof report.document.title === 'string'
                                                    ? report.document.title
                                                    : 'Captured report'}
                                            </h4>
                                            <LemonMarkdown disableImages="all">
                                                {trialReportText(report.document)}
                                            </LemonMarkdown>
                                            <LemonCollapse
                                                multiple
                                                size="small"
                                                panels={[
                                                    {
                                                        key: 'edits',
                                                        label: 'Changes made',
                                                        entries: report.edits,
                                                    },
                                                    {
                                                        key: 'evidence',
                                                        label: 'Evidence',
                                                        entries: report.evidence,
                                                    },
                                                    {
                                                        key: 'activity',
                                                        label: 'Report activity',
                                                        entries: report.artefacts,
                                                    },
                                                ].map(
                                                    ({ key, label, entries }) =>
                                                        !!entries?.length && {
                                                            key,
                                                            header: `${label} (${entries.length})`,
                                                            dataAttr: `scout-trial-report-${key}`,
                                                            content: (
                                                                <div className="flex flex-col gap-2 min-w-0">
                                                                    {entries.map((entry, index) => {
                                                                        const content =
                                                                            key === 'edits'
                                                                                ? entry.append_note
                                                                                : entry.content
                                                                        const text =
                                                                            typeof content === 'string'
                                                                                ? content
                                                                                : content &&
                                                                                    typeof content === 'object' &&
                                                                                    !Array.isArray(content) &&
                                                                                    'note' in content &&
                                                                                    typeof content.note === 'string'
                                                                                  ? content.note
                                                                                  : null
                                                                        return text ? (
                                                                            <LemonMarkdown
                                                                                key={index}
                                                                                disableImages="all"
                                                                            >
                                                                                {text}
                                                                            </LemonMarkdown>
                                                                        ) : null
                                                                    })}
                                                                    <LemonCollapse
                                                                        size="small"
                                                                        embedded
                                                                        panels={[
                                                                            {
                                                                                key: 'data',
                                                                                header: 'Captured data',
                                                                                content: (
                                                                                    <pre className="m-0 text-xs whitespace-pre-wrap break-words">
                                                                                        {JSON.stringify(
                                                                                            entries,
                                                                                            null,
                                                                                            2
                                                                                        )}
                                                                                    </pre>
                                                                                ),
                                                                            },
                                                                        ]}
                                                                    />
                                                                </div>
                                                            ),
                                                        }
                                                )}
                                            />
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p>No reports captured.</p>
                            ),
                        },
                        !!result && {
                            key: 'memory',
                            header: `Private memory changes (${memory.length})`,
                            content: memory.length ? (
                                <div className="flex flex-col gap-3">
                                    {memory.map(([key, entry]) => (
                                        <div key={key}>
                                            <strong className="break-all">{key}</strong>
                                            <p className="whitespace-pre-wrap break-words">
                                                {entry?.content ?? 'Deleted in this run'}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p>No memory changes recorded.</p>
                            ),
                        },
                        {
                            key: 'details',
                            header: 'Technical details',
                            content: (
                                <dl className="m-0 grid grid-cols-1 gap-1 text-xs break-all">
                                    <dt className="font-semibold">Run ID</dt>
                                    <dd className="m-0 mb-2">{selectedLaunchId}</dd>
                                    <dt className="font-semibold">Duration</dt>
                                    <dd className="m-0 mb-2">
                                        {duration !== null && duration >= 0
                                            ? formatRunDuration(duration)
                                            : 'Unavailable'}
                                    </dd>
                                    <dt className="font-semibold">Scout cost</dt>
                                    <dd className="m-0 mb-2">
                                        {result?.cost_usd == null ? 'Unavailable' : formatRunCost(result.cost_usd)}
                                    </dd>
                                    <dt className="font-semibold">Judge model</dt>
                                    <dd className="m-0 mb-2">{judgment ? report?.judge_model : 'Unavailable'}</dd>
                                    <dt className="font-semibold">Judging attempt</dt>
                                    <dd className="m-0 mb-2">{judgment ? report?.evaluation_id : 'Not judged'}</dd>
                                    <dt className="font-semibold">Judge prompt version</dt>
                                    <dd className="m-0 mb-2">
                                        {judgment ? report?.judge_prompt_version : 'Unavailable'}
                                    </dd>
                                    <dt className="font-semibold">Prompt fingerprint</dt>
                                    <dd className="m-0">
                                        {result?.skill_body_sha256 ?? evidence?.skill_body_sha256 ?? 'Unavailable'}
                                    </dd>
                                </dl>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonDrawer>
    )
}

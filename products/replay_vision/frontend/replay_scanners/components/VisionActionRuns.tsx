import { useValues } from 'kea'

import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { VisionActionRunApi, VisionActionRunStatusEnumApi } from '../../generated/api.schemas'
import { visionActionRunsLogic } from '../visionActionRunsLogic'

const STATUS_TAG: Record<
    VisionActionRunStatusEnumApi,
    { type: 'success' | 'danger' | 'warning' | 'primary'; label: string }
> = {
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
    skipped: { type: 'warning', label: 'Skipped' },
    running: { type: 'primary', label: 'Running' },
}

function RunMeta({ run }: { run: VisionActionRunApi }): JSX.Element {
    const tag = STATUS_TAG[run.status]
    const count = run.observation_count
    return (
        <div className="flex items-center gap-2 text-xs text-secondary">
            <LemonTag type={tag.type} size="small">
                {tag.label}
            </LemonTag>
            <TZLabel time={run.scheduled_at ?? run.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
            {count > 0 && <span>· Summarized {count === 1 ? '1 observation' : `${count} observations`}</span>}
        </div>
    )
}

function RunCard({ run }: { run: VisionActionRunApi }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3">
            <RunMeta run={run} />
            {run.synthesized_markdown ? (
                // The summary is the point of the run — give it the room.
                <LemonMarkdown className="text-base">{run.synthesized_markdown}</LemonMarkdown>
            ) : (
                <div className="text-muted italic">{run.error_reason || 'No summary was produced for this run.'}</div>
            )}
        </LemonCard>
    )
}

export function VisionActionRuns(): JSX.Element {
    const { runs, runsLoading } = useValues(visionActionRunsLogic)

    if (runsLoading && runs.length === 0) {
        return (
            <div className="flex justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (runs.length === 0) {
        return (
            <div className="text-muted p-8 text-center">
                This action hasn't run yet. Summaries will appear here once its schedule fires.
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {runs.map((run) => (
                <RunCard key={run.id} run={run} />
            ))}
        </div>
    )
}

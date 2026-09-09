import { useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowAction } from '../../types'
import {
    AI_TASKS_PER_WORKFLOW_PER_DAY,
    TRIGGER_VOLUME_DAYS,
    eventTriggerVolumeFilters,
    hogFlowStartsAiRuns,
} from '../triggerVolume'
import { triggerVolumeLogic } from '../triggerVolumeLogic'

/**
 * How often an event trigger fired recently, so an author sees the workload a workflow takes on
 * before they save it. Renders nothing for a trigger whose volume cannot be counted; the logic is
 * still bound in that case, because hooks cannot be skipped.
 */
export function TriggerVolumeEstimate({ action }: { action: HogFlowAction }): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)
    const filters = eventTriggerVolumeFilters(action)
    const { volume, volumeLoading, volumeFailed } = useValues(triggerVolumeLogic({ id: action.id, filters }))

    if (!filters) {
        return null
    }

    const startsAiRuns = hogFlowStartsAiRuns(workflow)
    const overAiLimit = startsAiRuns && volume != null && volume.perDay > AI_TASKS_PER_WORKFLOW_PER_DAY

    return (
        <div className="flex flex-col gap-2 w-full">
            <LemonLabel>Trigger volume</LemonLabel>
            {volumeLoading ? (
                <>
                    <p className="mb-0 text-secondary">Counting how often this trigger fired.</p>
                    <Sparkline type="bar" loading className="w-full h-16" data={[]} />
                </>
            ) : volumeFailed || !volume ? (
                <p className="mb-0 text-secondary">
                    Couldn't count how often this trigger fired. Check the filters above, then try again.
                </p>
            ) : (
                <>
                    <p className="mb-0">
                        This trigger matched <strong translate="no">{pluralize(volume.total, 'event')}</strong> in the
                        last {TRIGGER_VOLUME_DAYS} days, about{' '}
                        <span translate="no">{humanFriendlyNumber(volume.perDay)}</span> a day.
                    </p>
                    <Sparkline
                        type="bar"
                        className="w-full h-16"
                        data={volume.daily}
                        labels={volume.labels}
                        color={overAiLimit ? 'warning' : 'muted'}
                    />
                    {workflow.trigger_masking ? (
                        <p className="mb-0 text-secondary">
                            Your frequency limit is not in this count, so the workflow starts fewer runs than this.
                        </p>
                    ) : null}
                    {overAiLimit ? (
                        <LemonBanner type="warning">
                            Each run starts an AI task, and a workflow creates at most {AI_TASKS_PER_WORKFLOW_PER_DAY}{' '}
                            tasks a day. At this volume most runs would be skipped, and the tasks that do run count
                            toward your AI usage. Narrow the trigger with filters, or set a frequency limit.
                        </LemonBanner>
                    ) : startsAiRuns ? (
                        <p className="mb-0 text-secondary">
                            Each run starts an AI task, which counts toward your AI usage.
                        </p>
                    ) : null}
                </>
            )}
        </div>
    )
}

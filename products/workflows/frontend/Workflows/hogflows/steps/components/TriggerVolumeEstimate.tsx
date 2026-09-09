import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowAction } from '../../types'
import {
    DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY,
    TRIGGER_VOLUME_DAYS,
    countAiTaskSteps,
    countScoutSteps,
    eventTriggerVolumeFilters,
    exceedsAiTaskLimit,
} from '../triggerVolume'
import { triggerVolumeLogic } from '../triggerVolumeLogic'

/**
 * How often an event trigger fired recently, so an author sees the workload a workflow takes on
 * before they save it. Renders nothing for a trigger whose volume cannot be counted; the logic is
 * still bound in that case, because hooks cannot be skipped.
 */
export function TriggerVolumeEstimate({ action }: { action: HogFlowAction }): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)
    const filters = eventTriggerVolumeFilters(action)
    const { volume, volumeLoading, volumeFailed } = useValues(triggerVolumeLogic({ id: action.id, filters }))

    if (!filters) {
        return null
    }

    const taskSteps = countAiTaskSteps(workflow)
    const scoutSteps = countScoutSteps(workflow)
    // Every step a run reaches creates its own task, so the tasks a day is the runs a day times the
    // steps, not the runs alone.
    const aiTasksPerDay = volume != null ? volume.perDay * taskSteps : 0
    const overAiLimit = volume != null && exceedsAiTaskLimit(volume.peakPerDay, taskSteps)
    const perRunCopy =
        taskSteps > 1 ? `Each run can start up to ${taskSteps} AI tasks` : 'Each run can start an AI task'

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
                            Your frequency limit is not in this count, so the workflow may start fewer runs than this.
                        </p>
                    ) : null}
                    {overAiLimit ? (
                        <LemonBanner
                            type="warning"
                            action={
                                preflight?.cloud
                                    ? {
                                          children: 'Ask for a higher limit',
                                          onClick: () =>
                                              openSupportForm({
                                                  kind: 'support',
                                                  message: `Please raise the daily AI task limit for my workflow "${workflow.name}". Its trigger matches about ${humanFriendlyNumber(volume.perDay)} events a day, which is about ${humanFriendlyNumber(aiTasksPerDay)} AI tasks a day.`,
                                              }),
                                      }
                                    : undefined
                            }
                        >
                            {perRunCopy}, and a workflow stops at {DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY} AI tasks a day
                            by default. On its busiest day this trigger passes that limit, so runs above it get skipped,
                            and the tasks that do run count toward your AI usage.{' '}
                            {preflight?.cloud
                                ? 'Narrow the trigger with filters, set a frequency limit, or ask PostHog to raise the limit.'
                                : 'Narrow the trigger with filters, or set a frequency limit.'}
                        </LemonBanner>
                    ) : taskSteps > 0 ? (
                        <p className="mb-0 text-secondary">{perRunCopy}. AI tasks count toward your AI usage.</p>
                    ) : scoutSteps > 0 ? (
                        <p className="mb-0 text-secondary">
                            Each run can start a scout run, which counts toward your AI usage.
                        </p>
                    ) : null}
                </>
            )}
        </div>
    )
}

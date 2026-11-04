import { useValues } from 'kea'

import { IconBolt, IconChevronRight, IconClock, IconLeave, IconTarget } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { getDurationText } from '../hogflows/steps/stepDelayLogic'
import { workflowLogic } from '../workflowLogic'
import {
    EXIT_CONDITION_LABELS,
    conversionGoalEvents,
    frequencySummary,
    triggerEventNames,
    triggerLeadIn,
    triggerPropertyFilters,
} from './workflowOverviewSummary'

function DetailsSection({
    icon,
    title,
    editTo,
    editAttr,
    children,
}: {
    icon: JSX.Element
    title: string
    editTo: string
    editAttr: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 border-t px-4 py-3">
            <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 font-semibold">
                    <span className="flex text-lg text-secondary">{icon}</span>
                    {title}
                </span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    sideIcon={<IconChevronRight />}
                    to={editTo}
                    data-attr={editAttr}
                >
                    Edit
                </LemonButton>
            </div>
            <div className="flex flex-col gap-2 text-sm">{children}</div>
        </div>
    )
}

export function WorkflowOverviewDetails({ id }: { id: string }): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic)

    if (!originalWorkflow) {
        return <></>
    }

    const { trigger, conversion, exit_condition, email_sending_rate_limit, created_at, updated_at } = originalWorkflow
    const editTriggerUrl = `${urls.workflow(id, 'workflow')}?node=trigger_node`
    const eventNames = triggerEventNames(trigger)
    const propertyFilters = triggerPropertyFilters(trigger)
    const goalEvents = conversionGoalEvents(conversion)
    const goalProperties = conversion?.filters ?? []
    const goalWindow = conversion?.window ? getDurationText(conversion.window) : null
    const hasGoal = goalEvents.length > 0 || goalProperties.length > 0

    return (
        <div className="flex flex-col rounded border bg-surface-primary" data-attr="workflow-overview-details">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                <h3 className="mb-0 text-base font-semibold">Details</h3>
                <span className="flex flex-wrap items-center gap-2 text-xs text-muted">
                    <span>
                        Edited <TZLabel time={updated_at} />
                    </span>
                    <span>·</span>
                    <span>
                        Created <TZLabel time={created_at} />
                    </span>
                </span>
            </div>

            <DetailsSection
                icon={<IconBolt />}
                title="Trigger"
                editTo={editTriggerUrl}
                editAttr="workflow-overview-edit-trigger"
            >
                <span>
                    {triggerLeadIn(trigger)}
                    {eventNames.length > 0 ? ':' : '.'}
                </span>
                {eventNames.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                        {eventNames.map((name) => (
                            <LemonTag key={name} type="muted" className="font-mono">
                                {name}
                            </LemonTag>
                        ))}
                    </div>
                ) : null}
                {propertyFilters.length > 0 ? (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-muted">Only people matching</span>
                        <PropertyFiltersDisplay filters={propertyFilters} />
                    </div>
                ) : null}
                {trigger &&
                'filters' in trigger &&
                (trigger.filters as { filter_test_accounts?: boolean })?.filter_test_accounts ? (
                    <span className="text-xs text-muted">Internal and test accounts are excluded.</span>
                ) : null}
            </DetailsSection>

            <DetailsSection
                icon={<IconClock />}
                title="Frequency"
                editTo={editTriggerUrl}
                editAttr="workflow-overview-edit-frequency"
            >
                <span>{frequencySummary(originalWorkflow)}</span>
                {email_sending_rate_limit ? (
                    <span className="text-muted">
                        {`Emails send at most ${email_sending_rate_limit.count.toLocaleString()} per ${email_sending_rate_limit.period}.`}
                    </span>
                ) : null}
            </DetailsSection>

            <DetailsSection
                icon={<IconTarget />}
                title="Goal"
                editTo={editTriggerUrl}
                editAttr="workflow-overview-edit-goal"
            >
                {hasGoal ? (
                    <>
                        {goalEvents.length > 0 ? (
                            <div className="flex flex-wrap items-center gap-1">
                                <span>People convert when they perform</span>
                                {goalEvents.map((name) => (
                                    <LemonTag key={name} type="muted" className="font-mono">
                                        {name}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : null}
                        {goalProperties.length > 0 ? (
                            <div className="flex flex-col gap-1">
                                <span>
                                    {goalEvents.length > 0 ? 'or when they match' : 'People convert when they match'}
                                </span>
                                <PropertyFiltersDisplay filters={goalProperties} />
                            </div>
                        ) : null}
                        {goalWindow ? (
                            <span className="text-xs text-muted">
                                {`Counted within ${goalWindow} of entering the workflow.`}
                            </span>
                        ) : null}
                    </>
                ) : (
                    <span className="text-muted">
                        No conversion goal. Add one to measure what this workflow drives.
                    </span>
                )}
            </DetailsSection>

            <DetailsSection
                icon={<IconLeave />}
                title="Exit"
                editTo={editTriggerUrl}
                editAttr="workflow-overview-edit-exit"
            >
                <span>{EXIT_CONDITION_LABELS[exit_condition] ?? EXIT_CONDITION_LABELS.exit_only_at_end}</span>
            </DetailsSection>
        </div>
    )
}

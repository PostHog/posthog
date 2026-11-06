import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import type { HogFlowPublishImpactApi, HogFlowPublishImpactDeletedStepApi } from '../generated/api.schemas'

function PublishImpactContent({
    impact,
    inFlightRuns,
}: {
    impact: HogFlowPublishImpactApi | null
    inFlightRuns: number | null
}): JSX.Element {
    const deletedSteps = impact?.deleted_steps ?? []
    const emptyVariables = impact?.empty_variables ?? []
    const scheduleConflicts = impact?.schedule_conflicts ?? []

    return (
        <div className="flex flex-col gap-3">
            <p className="mb-0">
                This applies your staged changes to the live workflow.{' '}
                {inFlightRuns === null
                    ? 'The number of people currently mid-run could not be determined.'
                    : inFlightRuns === 0
                      ? 'No one is currently mid-run.'
                      : `${inFlightRuns} ${inFlightRuns === 1 ? 'person is' : 'people are'} currently mid-run and will continue on the published version.`}
            </p>
            {deletedSteps.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Removed steps</span>
                    <LemonTable<HogFlowPublishImpactDeletedStepApi>
                        dataSource={deletedSteps}
                        rowKey="action_id"
                        size="small"
                        columns={[
                            {
                                title: 'Step',
                                key: 'name',
                                render: (_, step) => step.name,
                            },
                            {
                                title: 'People here now',
                                key: 'runs',
                                render: (_, step) => (step.runs === null ? 'Unknown' : step.runs),
                            },
                            {
                                title: 'They will',
                                key: 'outcome',
                                render: (_, step) =>
                                    step.exits ? (
                                        <LemonTag type="danger">Exit the workflow</LemonTag>
                                    ) : (
                                        <span className="flex items-center gap-1">
                                            <IconArrowRight className="text-tertiary" />
                                            Move to {step.moves_to?.name ?? 'the next step'}
                                        </span>
                                    ),
                            },
                        ]}
                    />
                    {impact?.position_unknown ? (
                        <span className="text-xs text-secondary">
                            {impact.position_unknown} {impact.position_unknown === 1 ? 'person' : 'people'} mid-run
                            could not be placed at a specific step.
                        </span>
                    ) : null}
                </div>
            )}
            {emptyVariables.length > 0 && (
                <LemonBanner type="warning">
                    <div className="flex flex-col gap-1">
                        <span>Some variables may be empty for people already mid-run:</span>
                        <ul className="list-disc pl-4 mb-0">
                            {emptyVariables.map((variable) => (
                                <li key={variable.variable}>
                                    <code>{variable.variable}</code> is used by {variable.referenced_by.length}{' '}
                                    {variable.referenced_by.length === 1 ? 'step' : 'steps'} but only gets a value{' '}
                                    {variable.set_by ? 'from a step this draft adds or changes' : 'when a run starts'}.
                                </li>
                            ))}
                        </ul>
                    </div>
                </LemonBanner>
            )}
            {scheduleConflicts.length > 0 && (
                <LemonBanner type="warning">
                    {(() => {
                        const conflictVariables = new Set(scheduleConflicts.flatMap((conflict) => conflict.variables))
                        return `This draft removes ${
                            conflictVariables.size === 1 ? 'a variable' : `${conflictVariables.size} variables`
                        } that ${
                            scheduleConflicts.length === 1
                                ? 'an existing schedule still sets'
                                : 'existing schedules still set'
                        }. Review the schedules after publishing.`
                    })()}
                </LemonBanner>
            )}
        </div>
    )
}

export function openPublishConfirmDialog({
    impact,
    inFlightRuns,
    onConfirm,
}: {
    impact: HogFlowPublishImpactApi | null
    inFlightRuns: number | null
    onConfirm: () => void
}): void {
    LemonDialog.open({
        title: 'Publish staged changes?',
        maxWidth: '36rem',
        description: <PublishImpactContent impact={impact} inFlightRuns={inFlightRuns} />,
        primaryButton: {
            children: 'Publish',
            onClick: onConfirm,
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}

import { useValues } from 'kea'

import { LemonBanner, LemonCollapse, LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'

import { LogsViewerTable } from 'scenes/hog-functions/logs/LogsViewer'

import { renderWorkflowLogMessage } from '../../../logs/log-utils'
import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { TestRunStep, hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'

function stepOutcome(step: TestRunStep): { label: string; type: LemonTagType } {
    if (step.result.status === 'error') {
        return { label: 'Error', type: 'danger' }
    }
    if (step.result.status === 'skipped') {
        return { label: 'Skipped', type: 'warning' }
    }
    if (step.waitSkipped) {
        return { label: 'Wait skipped', type: 'muted' }
    }
    return { label: 'Success', type: 'success' }
}

export function HogFlowTestRunSteps(): JSX.Element {
    const { workflow, logicProps } = useValues(workflowLogic)
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const { testRunSteps, testRunning, testRunStopped } = useValues(hogFlowEditorTestLogic(logicProps))

    const stepName = (actionId: string): string =>
        workflow.actions.find((action) => action.id === actionId)?.name ?? actionId
    const failedStepIndex = testRunSteps?.findIndex((step) => step.result.status !== 'success') ?? -1

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-test-run-steps">
            {!!testRunSteps?.length && (
                <LemonCollapse
                    multiple
                    size="small"
                    defaultActiveKeys={failedStepIndex >= 0 ? [failedStepIndex] : []}
                    panels={(testRunSteps ?? []).map((step, index) => {
                        const outcome = stepOutcome(step)
                        return {
                            key: index,
                            header: (
                                <div className="flex flex-1 items-center justify-between gap-2 min-w-0">
                                    <span className="truncate">{stepName(step.actionId)}</span>
                                    <LemonTag type={outcome.type}>{outcome.label}</LemonTag>
                                </div>
                            ),
                            content: (
                                <div className="flex flex-col gap-2">
                                    {step.result.status === 'error' && (
                                        <LemonBanner type="error">{step.result.errors?.join(', ')}</LemonBanner>
                                    )}
                                    {step.result.status === 'skipped' && (
                                        <div className="text-secondary text-sm">
                                            The test event does not match the trigger filters, so a real run would not
                                            start.
                                        </div>
                                    )}
                                    {step.waitSkipped && (
                                        <div className="text-secondary text-sm">
                                            A real run waits here. The test moved straight on to the next step.
                                        </div>
                                    )}
                                    <LogsViewerTable
                                        instanceLabel="workflow run"
                                        renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
                                        dataSource={step.result.logs ?? []}
                                        renderColumns={(columns) =>
                                            columns.filter((column) => column.key !== 'instanceId')
                                        }
                                    />
                                </div>
                            ),
                        }
                    })}
                />
            )}
            {testRunStopped && <div className="text-secondary text-sm">The run was stopped.</div>}
            {testRunning && (
                <div className="flex items-center gap-2 text-secondary text-sm">
                    <Spinner />
                    <span>{`Running ${selectedNode?.data.name ?? 'the next step'}`}</span>
                </div>
            )}
        </div>
    )
}

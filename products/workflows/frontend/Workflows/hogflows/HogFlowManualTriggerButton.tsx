import { useActions, useValues } from 'kea'

import { IconButton, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, Popover } from '@posthog/lemon-ui'

import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputSchemaType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { WorkflowSceneLogicProps } from '../workflowSceneLogic'
import { hogFlowManualTriggerLogic } from './hogFlowManualTriggerLogic'

const VariableInputsPopover = ({
    setPopoverVisible,
}: {
    setPopoverVisible: (visible: boolean) => void
}): JSX.Element => {
    const { workflow } = useValues(workflowLogic)
    const { triggerManualWorkflow } = useActions(workflowLogic)
    const {
        inputs,
        useDefaults,
        scheduleEnabled,
        scheduledDateTime,
        variableValues,
        scheduleDisabledReason,
        timezone,
    } = useValues(hogFlowManualTriggerLogic({ id: workflow?.id || 'new' }))
    const { setInput, toggleUseDefaults, toggleScheduleEnabled, setScheduledDateTime } = useActions(
        hogFlowManualTriggerLogic({ id: workflow?.id || 'new' })
    )

    const noVariablesMessage = <div className="text-muted">No variables to configure.</div>

    const defaultVariableOption = (
        <div className="flex items-center gap-2">
            <LemonCheckbox label="Use default values" checked={useDefaults} onChange={() => toggleUseDefaults()} />
        </div>
    )

    const variableInputs = useDefaults ? (
        <>
            {workflow.variables?.map((variable: CyclotronJobInputSchemaType) => (
                <div key={variable.key} className="flex flex-col gap-1">
                    <label className="font-semibold">{variable.label || variable.key}</label>
                    <span className="text-xs text-muted">
                        {variable.default ? `Default: ${String(variable.default)}` : 'No default'}
                    </span>
                </div>
            ))}
        </>
    ) : (
        <>
            {workflow.variables?.map((variable: CyclotronJobInputSchemaType) => (
                <div key={variable.key} className="flex flex-col gap-1">
                    <LemonField.Pure className="font-semibold" label={variable.label}>
                        <LemonInput
                            type="text"
                            value={inputs[variable.key] ?? variable.default ?? ''}
                            placeholder={variable.default ? `Default: ${variable.default}` : ''}
                            onChange={(value) => setInput(variable.key, value)}
                            disabled={useDefaults}
                        />
                        {variable.default !== undefined && (
                            <span className="text-xs text-muted">
                                {variable.default ? `Default: ${String(variable.default)}` : 'No default'}
                            </span>
                        )}
                    </LemonField.Pure>
                </div>
            ))}
        </>
    )

    const scheduleSection = (
        <div className="flex flex-col gap-2 border-t pt-2">
            <LemonCheckbox
                label="Schedule for later"
                checked={scheduleEnabled}
                onChange={() => toggleScheduleEnabled()}
            />
            {scheduleEnabled && (
                <div className="flex flex-col gap-2">
                    <div className="text-xs text-muted">Project timezone: {timezone}</div>
                    <LemonCalendarSelectInput
                        value={scheduledDateTime}
                        onChange={(date) => {
                            // Interpret the selected wall-clock time in the team's timezone
                            setScheduledDateTime(date)
                        }}
                        granularity="minute"
                        selectionPeriod="upcoming"
                        showTimeToggle={false}
                    />
                </div>
            )}
        </div>
    )

    return (
        <div className="flex flex-col items-start gap-2 p-2 min-w-64">
            {!workflow?.variables || workflow.variables.length === 0 ? (
                noVariablesMessage
            ) : (
                <>
                    {defaultVariableOption}
                    {variableInputs}
                </>
            )}
            {scheduleSection}
            <div className="pt-2 flex justify-end w-full">
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => {
                        const scheduledAt =
                            scheduleEnabled && scheduledDateTime ? scheduledDateTime.toISOString() : undefined
                        ;(triggerManualWorkflow as any)(variableValues, scheduledAt)
                        setPopoverVisible(false)
                    }}
                    data-attr="run-workflow-btn"
                    sideIcon={<IconPlayFilled />}
                    disabledReason={scheduleDisabledReason}
                >
                    {scheduleEnabled ? 'Schedule workflow' : 'Run workflow'}
                </LemonButton>
            </div>
        </div>
    )
}

export const HogFlowManualTriggerButton = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = hogFlowManualTriggerLogic(props)
    const { manualTriggerPopoverVisible, workflow, workflowChanged } = useValues(logic)
    const { togglePopoverVisible } = useActions(logic)

    const triggerButton = (
        <LemonButton
            type="primary"
            disabledReason={
                workflow?.status !== 'active'
                    ? 'Must enable workflow to use trigger'
                    : workflowChanged
                      ? 'Save changes first'
                      : undefined
            }
            icon={<IconButton />}
            tooltip="Triggers workflow immediately"
            onClick={() => togglePopoverVisible()}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={manualTriggerPopoverVisible}
            placement="bottom-start"
            onClickOutside={() => togglePopoverVisible()}
            overlay={<VariableInputsPopover setPopoverVisible={togglePopoverVisible} />}
        >
            {triggerButton}
        </Popover>
    )
}

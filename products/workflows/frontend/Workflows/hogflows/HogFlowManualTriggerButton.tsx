import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonInput, Popover } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputSchemaType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../workflowLogic'
import { hogFlowManualTriggerButtonLogic } from './HogFlowManualTriggerButtonLogic'

const VariableInputsPopover = ({
    setPopoverVisible,
    props,
}: {
    setPopoverVisible: (visible: boolean) => void
    props: WorkflowLogicProps
}): JSX.Element => {
    const logic = hogFlowManualTriggerButtonLogic(props)
    const { workflow, variableValues, inputs } = useValues(logic)
    const { triggerManualWorkflow } = useActions(workflowLogic(props))
    const { setInput, clearInputs } = useActions(logic)

    if (!workflow?.variables || workflow.variables.length === 0) {
        return (
            <div className="flex flex-col gap-3 p-3 min-w-80">
                <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Configure variables</h3>
                </div>
                <div className="text-muted text-sm">No variables to configure.</div>
                <div className="flex justify-end border-t pt-3">
                    <LemonButton
                        type="primary"
                        status="alt"
                        onClick={() => {
                            triggerManualWorkflow({})
                            setPopoverVisible(false)
                            clearInputs()
                        }}
                        data-attr="run-workflow-btn"
                    >
                        Run workflow
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4 p-3 min-w-80 max-w-96">
            <div className="pb-2 border-b">
                <h3 className="text-sm font-semibold">Configure variables</h3>
                <p className="text-xs text-muted mt-0.5">Set variable values or leave empty to use defaults</p>
            </div>
            <div className="flex flex-col gap-3">
                {workflow.variables.map((variable: CyclotronJobInputSchemaType) => {
                    const inputValue = inputs[variable.key]
                    const displayValue = inputValue ?? ''
                    const hasDefault = variable.default !== undefined && variable.default !== ''

                    return (
                        <LemonField.Pure key={variable.key} label={variable.label || variable.key}>
                            {variable.type === 'number' ? (
                                <LemonInput
                                    type="number"
                                    value={displayValue === '' ? undefined : Number(displayValue)}
                                    placeholder={hasDefault ? `Default: ${String(variable.default)}` : 'Enter value'}
                                    onChange={(value: number | undefined) => {
                                        setInput(variable.key, value !== undefined ? String(value) : '')
                                    }}
                                />
                            ) : (
                                <LemonInput
                                    type="text"
                                    value={displayValue}
                                    placeholder={hasDefault ? `Default: ${String(variable.default)}` : 'Enter value'}
                                    onChange={(value: string) => {
                                        setInput(variable.key, value)
                                    }}
                                />
                            )}
                        </LemonField.Pure>
                    )
                })}
            </div>

            <div className="flex justify-end border-t pt-3">
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => {
                        triggerManualWorkflow(variableValues)
                        setPopoverVisible(false)
                        clearInputs()
                    }}
                    data-attr="run-workflow-btn"
                >
                    Run workflow
                </LemonButton>
            </div>
        </div>
    )
}

export const HogFlowManualTriggerButton = (props: WorkflowLogicProps = {}): JSX.Element => {
    const logic = hogFlowManualTriggerButtonLogic(props)
    const { workflow, workflowChanged } = useValues(workflowLogic(props))
    const { popoverVisible } = useValues(logic)
    const { setPopoverVisible } = useActions(logic)

    const triggerButton = (
        <LemonButton
            type="primary"
            size="small"
            disabledReason={
                workflow?.status !== 'active'
                    ? 'Must enable workflow to use trigger'
                    : workflowChanged
                      ? 'Save changes first'
                      : undefined
            }
            sideIcon={<IconChevronDown className={`transition-transform ${popoverVisible ? 'rotate-180' : ''}`} />}
            tooltip="Triggers workflow immediately"
            onClick={() => setPopoverVisible(!popoverVisible)}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={popoverVisible}
            placement="bottom-start"
            onClickOutside={() => setPopoverVisible(false)}
            overlay={<VariableInputsPopover setPopoverVisible={setPopoverVisible} props={props} />}
        >
            {triggerButton}
        </Popover>
    )
}

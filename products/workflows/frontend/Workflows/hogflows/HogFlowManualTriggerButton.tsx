import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonInput, Popover } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputSchemaType } from '~/types'

import { workflowLogic } from '../workflowLogic'

const VariableInputsPopover = ({
    setPopoverVisible,
}: {
    setPopoverVisible: (visible: boolean) => void
}): JSX.Element => {
    const { workflow } = useValues(workflowLogic)
    const { triggerManualWorkflow } = useActions(workflowLogic)
    const [inputs, setInputs] = useState<Record<string, string>>({})

    const getVariableValues = (): Record<string, string> => {
        if (!workflow?.variables) {
            return {}
        }
        return Object.fromEntries(
            workflow.variables.map((v: any) => {
                const inputValue = inputs[v.key]
                // Use input value if provided and not empty, otherwise use default
                return [v.key, inputValue !== undefined && inputValue !== '' ? inputValue : (v.default ?? '')]
            })
        )
    }

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
                            <LemonInput
                                type="text"
                                value={displayValue}
                                placeholder={hasDefault ? `Default: ${String(variable.default)}` : 'Enter value'}
                                onChange={(value) => {
                                    setInputs((prev) => ({ ...prev, [variable.key]: value }))
                                }}
                            />
                        </LemonField.Pure>
                    )
                })}
            </div>

            <div className="flex justify-end border-t pt-3">
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => {
                        triggerManualWorkflow(getVariableValues())
                        setPopoverVisible(false)
                    }}
                    data-attr="run-workflow-btn"
                >
                    Run workflow
                </LemonButton>
            </div>
        </div>
    )
}

export const HogFlowManualTriggerButton = (): JSX.Element => {
    const { workflow, workflowChanged } = useValues(workflowLogic)
    const [manualTriggerPopoverVisible, setManualTriggerPopoverVisible] = useState(false)

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
            sideIcon={
                <IconChevronDown
                    className={`transition-transform ${manualTriggerPopoverVisible ? 'rotate-180' : ''}`}
                />
            }
            tooltip="Triggers workflow immediately"
            onClick={() => setManualTriggerPopoverVisible(!manualTriggerPopoverVisible)}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={manualTriggerPopoverVisible}
            placement="bottom-start"
            onClickOutside={() => setManualTriggerPopoverVisible(false)}
            overlay={<VariableInputsPopover setPopoverVisible={setManualTriggerPopoverVisible} />}
        >
            {triggerButton}
        </Popover>
    )
}

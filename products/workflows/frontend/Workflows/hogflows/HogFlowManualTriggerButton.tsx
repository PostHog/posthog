import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconButton, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, Popover } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputSchemaType } from '~/types'

import { workflowLogic } from '../workflowLogic'

const VariableInputsPopover: React.FC = () => {
    const { workflow } = useValues(workflowLogic)
    const { triggerManualWorkflow } = useActions(workflowLogic)
    const [inputs, setInputs] = useState<Record<string, string>>({})
    const [useDefaults, setUseDefaults] = useState(true)

    const handleInputChange = (key: string, value: string) => {
        setInputs((prev) => ({ ...prev, [key]: value }))
    }

    // Helper to build the variable values to send
    const getVariableValues = () => {
        if (!workflow?.variables) return {}
        if (useDefaults) {
            return Object.fromEntries(workflow.variables.map((v: any) => [v.key, v.default ?? '']))
        } else {
            return Object.fromEntries(workflow.variables.map((v: any) => [v.key, inputs[v.key] ?? v.default ?? '']))
        }
    }

    const noVariablesMessage = <div className="text-muted">No variables to configure.</div>

    const defaultVariableOption = (
        <div className="flex items-center gap-2">
            <LemonCheckbox
                label="Use default values"
                checked={useDefaults}
                onChange={() => setUseDefaults((v) => !v)}
            />
        </div>
    )

    const variableInputs = useDefaults ? (
        <>
            {workflow.variables?.map((variable: CyclotronJobInputSchemaType) => (
                <div key={variable.key} className="flex flex-col gap-1">
                    <label className="font-semibold">{variable.label || variable.key}</label>
                    <span className="text-xs text-muted">
                        {variable.default !== undefined ? `Default: ${String(variable.default)}` : 'No default'}
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
                            onChange={(value) => handleInputChange(variable.key, value)}
                            disabled={useDefaults}
                        />
                        {variable.default !== undefined && (
                            <span className="text-xs text-muted">Default: {String(variable.default)}</span>
                        )}
                    </LemonField.Pure>
                </div>
            ))}
        </>
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
            <div className="pt-2 flex justify-end">
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => triggerManualWorkflow(getVariableValues())}
                    data-attr="run-workflow-btn"
                    sideIcon={<IconPlayFilled />}
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
            icon={<IconButton />}
            tooltip="Triggers workflow immediately"
            onClick={() => setManualTriggerPopoverVisible(true)}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={manualTriggerPopoverVisible}
            placement="bottom-start"
            onClickOutside={() => setManualTriggerPopoverVisible(false)}
            overlay={<VariableInputsPopover />}
        >
            {triggerButton}
        </Popover>
    )
}

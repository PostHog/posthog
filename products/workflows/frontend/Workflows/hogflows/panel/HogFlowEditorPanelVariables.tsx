import { useActions, useValues } from 'kea'

import { IconCode, IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelVariables(): JSX.Element | null {
    const { workflow } = useValues(hogFlowEditorLogic)
    const { setWorkflowInfo } = useActions(hogFlowEditorLogic)

    const addNewVariable = (): void => {
        const newVariableName = `VARIABLE_${(workflow?.variables?.length || 0) + 1}`
        const updatedVariables = [
            ...(workflow?.variables || []),
            { key: newVariableName, label: newVariableName, type: 'string' as const, default_value: '' },
        ]
        setWorkflowInfo({
            variables: updatedVariables,
        })
    }

    const editVariableKey = (idx: number, key: string): void => {
        const updatedVariables = [...(workflow?.variables || [])]
        const sanitizedKey = key.replace(/\s+/g, '_')
        updatedVariables[idx].key = sanitizedKey
        updatedVariables[idx].label = sanitizedKey
        setWorkflowInfo({
            variables: updatedVariables,
        })
    }

    const editVariableDefaultValue = (idx: number, defaultValue: string): void => {
        const updatedVariables = [...(workflow?.variables || [])]
        updatedVariables[idx].default = defaultValue
        setWorkflowInfo({
            variables: updatedVariables,
        })
    }

    const deleteVariable = (idx: number): void => {
        LemonDialog.open({
            title: 'Delete variable',
            description: `Are you sure you want to delete the variable "${workflow.variables?.[idx]?.key}"?`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => {
                    const newVariables = [...(workflow?.variables || [])]
                    newVariables.splice(idx, 1)
                    setWorkflowInfo({ variables: newVariables })
                },
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col items-start m-2 gap-2">
            <LemonLabel
                info={
                    <>
                        <span>
                            These variables can be used by actions and conditions in this workflow. Use{' '}
                            <code>{`{ variable_name }`}</code> to reference a variable in an action or condition. You
                            can also set variables using the result of an action by selecting a node and configuring the
                            "Output variable" section.
                        </span>
                    </>
                }
            >
                <IconCode className="text-lg" /> Workflow variables
            </LemonLabel>

            {workflow.variables?.map((variable, idx) => (
                <div key={`${workflow.id}_${idx}`} className="w-full flex flex-grow items-end justify-end gap-2">
                    <LemonField.Pure className="w-36" label="Key">
                        <LemonInput
                            type="text"
                            value={variable.key}
                            placeholder="Unique name"
                            onChange={(key) => {
                                editVariableKey(idx, key)
                            }}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Default value" className="flex-1">
                        <LemonInput
                            type="text"
                            value={workflow?.variables?.[idx]?.default || ''}
                            placeholder="Default value"
                            onChange={(defaultValue) => {
                                editVariableDefaultValue(idx, defaultValue)
                            }}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Usage syntax">
                        <Tooltip title={`{{ variables.${variable.key} }}`}>
                            <span className="group relative">
                                <code className="w-36 py-2 bg-primary-alt-highlight-light rounded-sm text-center text-xs truncate block">
                                    {`{{ variables.${variable.key} }}`}
                                </code>
                                <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                                    <LemonButton
                                        size="small"
                                        icon={<IconCopy />}
                                        className="bg-white/80"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            void navigator.clipboard.writeText(`{{ variables.${variable.key} }}`)
                                            lemonToast.success('Copied to clipboard')
                                        }}
                                    />
                                </span>
                            </span>
                        </Tooltip>
                    </LemonField.Pure>
                    <LemonButton
                        icon={<IconTrash />}
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            deleteVariable(idx)
                        }}
                    />
                </div>
            ))}
            <LemonButton icon={<IconPlus />} type="secondary" size="small" onClick={addNewVariable}>
                New variable
            </LemonButton>
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { IconCode, IconCopy, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, lemonToast } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelVariables(): JSX.Element | null {
    const { workflow } = useValues(hogFlowEditorLogic)
    const { setWorkflowInfo } = useActions(hogFlowEditorLogic)

    const addNewVariable = (): void => {
        const newVariableName = `VARIABLE_${(workflow?.variables?.length || 0) + 1}`
        const updatedVariables = [
            ...(workflow?.variables || []),
            { key: newVariableName, label: newVariableName, type: 'string' as const, default: '' },
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
        <div className="flex flex-col h-full overflow-hidden m-2 max-w-2xl">
            <LemonLabel
                info={
                    <span>
                        These variables can be used by actions and conditions in this workflow. Use{' '}
                        <code>{`{ variable_name }`}</code> to reference a variable in an action or condition. You can
                        also set variables using the result of an action by selecting a node and configuring the "Output
                        variable" section.
                    </span>
                }
            >
                <IconCode className="text-lg" /> Workflow variables
            </LemonLabel>

            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="flex flex-col gap-1.5 py-2"
                styledScrollbars
            >
                {workflow.variables && workflow.variables.length > 0 && (
                    <div className="w-full flex gap-2 px-0.5 text-xs font-medium text-secondary">
                        <span className="w-32">Key</span>
                        <span className="w-40">Default</span>
                        <span className="flex-1">Usage</span>
                        <span className="w-5" />
                    </div>
                )}

                {workflow.variables?.map((variable, idx) => (
                    <div key={`${workflow.id}_${idx}`} className="w-full flex items-center gap-2">
                        <LemonField.Pure className="w-32">
                            <LemonInput
                                size="small"
                                type="text"
                                value={variable.key}
                                placeholder="Unique name"
                                onChange={(key) => {
                                    editVariableKey(idx, key)
                                }}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure className="w-40">
                            <LemonInput
                                size="small"
                                type="text"
                                value={workflow?.variables?.[idx]?.default || ''}
                                placeholder="Default value"
                                onChange={(defaultValue) => {
                                    editVariableDefaultValue(idx, defaultValue)
                                }}
                            />
                        </LemonField.Pure>
                        <span className="group relative flex-1">
                            <code className="w-full py-1 bg-primary-alt-highlight-secondary rounded-sm text-center text-xs truncate block">
                                {`{ variables.${variable.key} }`}
                            </code>
                            <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                                <LemonButton
                                    size="small"
                                    icon={<IconCopy />}
                                    className="bg-white/80"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        void navigator.clipboard.writeText(`{ variables.${variable.key} }`)
                                        lemonToast.success('Copied to clipboard')
                                    }}
                                />
                            </span>
                        </span>
                        <LemonButton
                            size="small"
                            icon={<IconX />}
                            onClick={() => {
                                deleteVariable(idx)
                            }}
                        />
                    </div>
                ))}
                <LemonButton
                    icon={<IconPlus />}
                    type="secondary"
                    size="small"
                    className="self-start"
                    onClick={addNewVariable}
                >
                    New variable
                </LemonButton>
            </ScrollableShadows>
        </div>
    )
}

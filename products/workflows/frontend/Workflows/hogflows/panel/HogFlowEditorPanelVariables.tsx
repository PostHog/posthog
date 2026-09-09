import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelVariables(): JSX.Element | null {
    const { workflow } = useValues(hogFlowEditorLogic)
    const { setWorkflowInfo } = useActions(hogFlowEditorLogic)
    const [hoveredVariableIndex, setHoveredVariableIndex] = useState<number | null>(null)
    const [editingVariableIndex, setEditingVariableIndex] = useState<number | null>(null)
    const [deletingVariableIndex, setDeletingVariableIndex] = useState<number | null>(null)
    const [variableKeyDraft, setVariableKeyDraft] = useState('')

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
        const sanitizedKey = key.replace(/\s+/g, '_')
        setWorkflowInfo({
            variables: (workflow?.variables || []).map((variable, index) =>
                index === idx ? { ...variable, key: sanitizedKey, label: sanitizedKey } : variable
            ),
        })
    }

    const editVariableDefaultValue = (idx: number, defaultValue: string): void => {
        setWorkflowInfo({
            variables: (workflow?.variables || []).map((variable, index) =>
                index === idx ? { ...variable, default: defaultValue } : variable
            ),
        })
    }

    const showVariableKeyInput = (idx: number, key: string): void => {
        setHoveredVariableIndex(idx)
        if (editingVariableIndex === null) {
            setVariableKeyDraft(key)
        }
    }

    const finishEditingVariableKey = (idx: number): void => {
        editVariableKey(idx, variableKeyDraft)
        setEditingVariableIndex(null)
        setHoveredVariableIndex(null)
    }

    const deleteVariable = (idx: number): void => {
        const newVariables = [...(workflow?.variables || [])]
        newVariables.splice(idx, 1)
        setWorkflowInfo({ variables: newVariables })
        setDeletingVariableIndex(null)
    }

    return (
        <div className="flex h-full flex-col overflow-hidden">
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="flex flex-col"
                styledScrollbars
            >
                {workflow.variables?.map((variable, idx) => (
                    <div key={`${workflow.id}_${idx}`} className="flex items-center gap-2 border-b px-3 py-2">
                        {deletingVariableIndex === idx ? (
                            <div className="flex min-w-0 flex-1 items-center justify-between gap-2 text-sm">
                                <span>
                                    Delete <code className="font-mono">{variable.key}</code>?
                                </span>
                                <div className="flex shrink-0 gap-1">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        status="danger"
                                        onClick={() => deleteVariable(idx)}
                                    >
                                        Delete
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        onClick={() => setDeletingVariableIndex(null)}
                                    >
                                        Cancel
                                    </LemonButton>
                                </div>
                            </div>
                        ) : (
                            <>
                                <div
                                    className="min-w-0 flex-1"
                                    onMouseEnter={() => showVariableKeyInput(idx, variable.key)}
                                    onMouseLeave={() => {
                                        if (hoveredVariableIndex === idx && editingVariableIndex !== idx) {
                                            setHoveredVariableIndex(null)
                                        }
                                    }}
                                >
                                    {editingVariableIndex === idx ||
                                    (editingVariableIndex === null && hoveredVariableIndex === idx) ? (
                                        <LemonInput
                                            className="font-mono text-xs"
                                            size="small"
                                            type="text"
                                            value={variableKeyDraft}
                                            placeholder="Unique name"
                                            aria-label="Variable key"
                                            autoFocus={editingVariableIndex === idx}
                                            prefix={<code className="text-xs text-secondary">{'{{ variables.'}</code>}
                                            suffix={<code className="text-xs text-secondary">{' }}'}</code>}
                                            onChange={setVariableKeyDraft}
                                            onFocus={() => setEditingVariableIndex(idx)}
                                            onBlur={() => finishEditingVariableKey(idx)}
                                            onPressEnter={(event) => event.currentTarget.blur()}
                                        />
                                    ) : (
                                        <button
                                            type="button"
                                            className="block w-full truncate rounded-sm bg-primary-alt-highlight-secondary px-2 py-1.5 text-left text-xs hover:bg-primary-alt-highlight"
                                            onClick={() => {
                                                showVariableKeyInput(idx, variable.key)
                                                setEditingVariableIndex(idx)
                                            }}
                                        >
                                            <code>{`{{ variables.${variable.key} }}`}</code>
                                        </button>
                                    )}
                                </div>
                                <LemonField.Pure className="w-2/5 shrink-0">
                                    <LemonInput
                                        size="small"
                                        type="text"
                                        value={String(variable.default ?? '')}
                                        placeholder="Default value"
                                        onChange={(defaultValue) => editVariableDefaultValue(idx, defaultValue)}
                                    />
                                </LemonField.Pure>
                                <LemonButton
                                    size="small"
                                    type="tertiary"
                                    icon={<IconX />}
                                    tooltip="Delete variable"
                                    aria-label={`Delete ${variable.key || 'variable'}`}
                                    onClick={() => {
                                        setHoveredVariableIndex(null)
                                        setEditingVariableIndex(null)
                                        setDeletingVariableIndex(idx)
                                    }}
                                />
                            </>
                        )}
                    </div>
                ))}
            </ScrollableShadows>
            <div className="shrink-0 px-3 py-2">
                <LemonButton icon={<IconPlus />} type="secondary" size="small" onClick={addNewVariable}>
                    New variable
                </LemonButton>
            </div>

            <LemonDivider className="my-0 shrink-0" />
            <LemonCollapse
                embedded
                className="shrink-0"
                panels={[
                    {
                        key: 'variable-usage',
                        header: <span className="flex-1">How to use variables</span>,
                        content: (
                            <div className="flex flex-col gap-3 text-sm text-secondary">
                                <p>
                                    Use a variable reference in any action input or condition. For example, enter{' '}
                                    <code>{`{{ variables.account_owner }}`}</code> as an input value.
                                </p>
                                <p>
                                    To save a step result into a variable, select the step and use its{' '}
                                    <strong>Output variables</strong> section.
                                </p>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import {
    OutputMapping,
    WORKFLOW_VARIABLE_TYPE_OPTIONS,
    hogFlowOutputMappingLogic,
    sanitizeAgentFieldName,
} from './hogFlowOutputMappingLogic'

// Mirrors the tasks API caps (RESULT_BYTE_CAP, RESULT_STRING_CAP): past them the result is cut silently.
const RESULT_BYTE_CAP = 4096
const RESULT_STRING_CAP = 1500

const AGENT_FIELD_PATH = /^output\.([A-Za-z_][A-Za-z0-9_]*)$/

const BUILT_IN_RESULTS = [
    { key: 'final_message', result_path: 'final_message', label: 'Final message' },
    { key: 'pr_urls', result_path: 'pr_urls', label: 'PR links' },
]

function builtInLabel(resultPath: string): string {
    if (!resultPath) {
        return 'Whole result'
    }
    return BUILT_IN_RESULTS.find((r) => r.result_path === resultPath)?.label ?? 'Run result'
}

function worstCaseBytes(fields: { name: string; type?: string }[]): number {
    return fields.reduce((sum, { name, type }) => {
        const value = type === 'number' ? 20 : type === 'boolean' ? 5 : type === 'json' ? 0 : RESULT_STRING_CAP + 2
        return sum + name.length + 4 + value
    }, 2)
}

function AgentFieldNameInput({
    name,
    variable,
    onCommit,
}: {
    name: string
    variable: string
    onCommit: (name: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(name)
    useEffect(() => setDraft(name), [name])
    const commit = (): void => {
        if (draft !== name) {
            onCommit(draft)
        }
        // A refused name (one another field already uses) snaps back to the saved one.
        setDraft(name)
    }
    return (
        <LemonInput
            size="small"
            value={draft}
            placeholder="summary"
            onChange={(value) => setDraft(sanitizeAgentFieldName(value))}
            onBlur={commit}
            onPressEnter={commit}
            suffix={
                variable && variable !== name ? (
                    <span className="text-xs text-secondary">{`saved to ${variable}`}</span>
                ) : undefined
            }
        />
    )
}

// Commits on blur, so a half-typed path is never saved and an `output.<name>` path gets the agent field checks.
function ResultPathInput({ path, onCommit }: { path: string; onCommit: (path: string) => void }): JSX.Element {
    const [draft, setDraft] = useState(path)
    useEffect(() => setDraft(path), [path])
    const commit = (): void => {
        if (draft !== path) {
            onCommit(draft.trim())
        }
        setDraft(path)
    }
    return (
        <LemonInput
            size="small"
            prefix={<span>result.</span>}
            value={draft}
            placeholder="Whole result"
            onChange={setDraft}
            onBlur={commit}
            onPressEnter={commit}
        />
    )
}

export function AiTaskReturns(): JSX.Element {
    const { logicProps, workflow } = useValues(workflowLogic)
    const { mappings } = useValues(hogFlowOutputMappingLogic(logicProps))
    const {
        setAgentField,
        setVariableType,
        setVariableDescription,
        addMapping,
        removeMapping,
        applySuggestion,
        updateMappingResultPath,
    } = useActions(hogFlowOutputMappingLogic(logicProps))

    const variableFor = (key: string): NonNullable<typeof workflow.variables>[number] | undefined =>
        workflow.variables?.find((v) => v.key === key)
    const rows = mappings.map((mapping: OutputMapping, index) => {
        const fieldName = AGENT_FIELD_PATH.exec(mapping.result_path)?.[1]
        return { mapping, index, isAgentField: !!fieldName || (!mapping.key && !mapping.result_path), fieldName }
    })
    const agentFields = rows.filter((row) => row.isAgentField && row.fieldName)
    const hasJsonField = agentFields.some((row) => variableFor(row.mapping.key)?.type === 'json')
    const overBudget =
        worstCaseBytes(agentFields.map((row) => ({ name: row.fieldName!, type: variableFor(row.mapping.key)?.type }))) >
        RESULT_BYTE_CAP
    const missingBuiltIns = BUILT_IN_RESULTS.filter(
        (r) => !mappings.some((m) => m.result_path === r.result_path || m.key === r.key)
    )

    return (
        <div className="flex flex-col gap-2 w-full">
            {rows.length > 0 && (
                <div className="grid grid-cols-[1fr_9rem_1.5fr_auto] gap-1 items-center">
                    <span className="text-xs text-secondary font-semibold">Field</span>
                    <span className="text-xs text-secondary font-semibold">Type</span>
                    <span className="text-xs text-secondary font-semibold">What the agent puts here</span>
                    <span />
                    {rows.map(({ mapping, index, isAgentField, fieldName }) => {
                        const variable = variableFor(mapping.key)
                        const remove = (
                            <LemonButton
                                key={`remove-${index}`}
                                size="small"
                                icon={<IconX />}
                                tooltip="Remove field"
                                onClick={() => removeMapping(index)}
                            />
                        )
                        if (!isAgentField) {
                            return [
                                <ResultPathInput
                                    key={`name-${index}`}
                                    path={mapping.result_path}
                                    onCommit={(path) => {
                                        const agentField = AGENT_FIELD_PATH.exec(path)?.[1]
                                        if (agentField) {
                                            setAgentField(index, sanitizeAgentFieldName(agentField))
                                        } else {
                                            updateMappingResultPath(index, path)
                                        }
                                    }}
                                />,
                                <span key={`type-${index}`} className="text-xs text-secondary px-2">
                                    {builtInLabel(mapping.result_path)}
                                </span>,
                                <span key={`desc-${index}`} className="text-xs text-secondary px-2">
                                    Saved to <code>{`{variables.${mapping.key}}`}</code>
                                </span>,
                                remove,
                            ]
                        }
                        return [
                            <AgentFieldNameInput
                                key={`name-${index}`}
                                name={fieldName ?? ''}
                                variable={mapping.key}
                                onCommit={(name) => setAgentField(index, name)}
                            />,
                            <LemonSelect
                                key={`type-${index}`}
                                size="small"
                                options={WORKFLOW_VARIABLE_TYPE_OPTIONS}
                                value={
                                    WORKFLOW_VARIABLE_TYPE_OPTIONS.find((o) => o.value === variable?.type)?.value ??
                                    'string'
                                }
                                disabledReason={!fieldName ? 'Name the field first.' : undefined}
                                onChange={(type) => type && setVariableType(mapping.key, type)}
                            />,
                            <LemonInput
                                key={`desc-${index}`}
                                size="small"
                                value={variable?.description ?? ''}
                                placeholder="Describe the value"
                                maxLength={200}
                                disabledReason={!fieldName ? 'Name the field first.' : undefined}
                                onChange={(description) => setVariableDescription(mapping.key, description)}
                            />,
                            remove,
                        ]
                    })}
                </div>
            )}
            <div className="flex flex-wrap gap-1">
                <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={() => addMapping()}>
                    Add field
                </LemonButton>
                {missingBuiltIns.map((builtIn) => (
                    <LemonButton
                        key={builtIn.key}
                        size="small"
                        type="tertiary"
                        icon={<IconPlus />}
                        onClick={() => applySuggestion(builtIn)}
                    >
                        {builtIn.label}
                    </LemonButton>
                ))}
            </div>
            {agentFields.length > 0 && (
                <span className="text-xs text-secondary">
                    Each field is saved as a workflow variable, such as{' '}
                    <code>{`{variables.${agentFields[0].mapping.key}}`}</code>.
                </span>
            )}
            {(overBudget || hasJsonField) && (
                <LemonBanner type="warning">
                    The workflow keeps about 4 KB from the agent, and anything past that is cut off.{' '}
                    {overBudget
                        ? `Each text field can hold up to ${RESULT_STRING_CAP} characters, so remove a text field or switch one to a number or true or false.`
                        : 'A JSON field has no fixed size, so describe a small shape for it.'}
                </LemonBanner>
            )}
        </div>
    )
}

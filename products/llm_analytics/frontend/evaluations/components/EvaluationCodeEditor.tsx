import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { HogTestResult } from '../types'

const HOG_EXAMPLES: { label: string; source: string }[] = [
    {
        label: 'Output not empty',
        source: `// Check that the output is not empty
let result := length(output) > 0
if (not result) {
    print('Output is empty')
}
return result`,
    },
    {
        label: 'Min output length',
        source: `// Check that the output is at least 100 characters
let result := length(output) >= 100
if (not result) {
    print('Output too short:', length(output), 'chars')
}
return result`,
    },
    {
        label: 'Contains keyword',
        source: `// Check that the output contains an expected keyword
let keyword := 'hello'
let result := output ilike concat('%', keyword, '%')
if (not result) {
    print('Missing keyword:', keyword)
}
return result`,
    },
    {
        label: 'Print messages',
        source: `// Print each message and always pass
let messages := input
if (typeof(messages) == 'string') {
    messages := jsonParse(messages)
}
if (typeof(messages) == 'array') {
    for (let i, msg in messages) {
        print(concat('Message ', toString(i), ': [', msg.role, '] ', msg.content))
    }
} else {
    print('Input:', messages)
}
return true`,
    },
    {
        label: 'Valid JSON output',
        source: `// Check that the output is valid JSON
fn isValidJSON(s) {
    try {
        jsonParse(s)
        return true
    } catch (e) {
        return false
    }
}

let result := isValidJSON(output)
if (not result) {
    print('Output is not valid JSON')
}
return result`,
    },
]

const HOG_EVAL_GLOBALS: Record<string, any> = {
    input: {
        type: 'string',
        description: 'The input to the LLM (prompt / messages)',
    },
    output: {
        type: 'string',
        description: 'The output from the LLM (response / choices)',
    },
    properties: {
        type: 'object',
        description: 'All event properties',
    },
    event: {
        uuid: { type: 'string' },
        event: { type: 'string' },
        distinct_id: { type: 'string' },
    },
}

function HogTestResultsPanel(): JSX.Element | null {
    const { hogTestResults, hogTestResultsLoading } = useValues(llmEvaluationLogic)
    const { clearHogTestResults } = useActions(llmEvaluationLogic)

    if (!hogTestResults && !hogTestResultsLoading) {
        return null
    }

    const passed = hogTestResults?.filter((r) => r.result === true).length ?? 0
    const failed = hogTestResults?.filter((r) => r.result === false).length ?? 0
    const errors = hogTestResults?.filter((r) => r.error !== null).length ?? 0

    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-sm">
                    <span className="font-semibold">Test results</span>
                    {hogTestResults && (
                        <>
                            <LemonTag type="success" icon={<IconCheck />}>
                                {passed} passed
                            </LemonTag>
                            <LemonTag type="danger" icon={<IconX />}>
                                {failed} failed
                            </LemonTag>
                            {errors > 0 && (
                                <LemonTag type="danger" icon={<IconWarning />}>
                                    {errors} errors
                                </LemonTag>
                            )}
                        </>
                    )}
                </div>
                <LemonButton type="secondary" size="xsmall" onClick={clearHogTestResults}>
                    Clear
                </LemonButton>
            </div>
            <LemonTable<HogTestResult>
                columns={[
                    {
                        title: 'Result',
                        key: 'result',
                        width: 100,
                        render: (_, row) => {
                            if (row.error) {
                                return (
                                    <Tooltip title={row.error}>
                                        <span>
                                            <LemonTag type="danger" icon={<IconWarning />}>
                                                Error
                                            </LemonTag>
                                        </span>
                                    </Tooltip>
                                )
                            }
                            return row.result ? (
                                <LemonTag type="success" icon={<IconCheck />}>
                                    Pass
                                </LemonTag>
                            ) : (
                                <LemonTag type="danger" icon={<IconX />}>
                                    Fail
                                </LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Output preview',
                        key: 'output_preview',
                        render: (_, row) => (
                            <Tooltip title={row.output_preview}>
                                <div className="max-w-xs truncate text-sm cursor-default">
                                    {row.output_preview || <span className="text-muted italic">empty</span>}
                                </div>
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Reasoning',
                        key: 'reasoning',
                        render: (_, row) => (
                            <Tooltip title={row.reasoning || row.error}>
                                <div className="max-w-xs truncate text-sm cursor-default">
                                    {row.reasoning || row.error || <span className="text-muted italic">none</span>}
                                </div>
                            </Tooltip>
                        ),
                    },
                ]}
                dataSource={hogTestResults ?? []}
                loading={hogTestResultsLoading}
                rowKey="event_uuid"
                size="small"
            />
        </div>
    )
}

export function EvaluationCodeEditor(): JSX.Element {
    const { evaluation, hogTestResultsLoading } = useValues(llmEvaluationLogic)
    const { setHogSource, testHogOnSample } = useActions(llmEvaluationLogic)

    if (!evaluation || evaluation.evaluation_type !== 'hog') {
        return <div>Loading...</div>
    }

    const source = evaluation.evaluation_config.source

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <CodeEditorResizeable
                    language="hog"
                    value={source}
                    onChange={(v) => setHogSource(v ?? '')}
                    globals={HOG_EVAL_GLOBALS}
                    minHeight="12rem"
                    maxHeight="60vh"
                    options={{
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        fixedOverflowWidgets: true,
                        suggest: { showInlineDetails: true },
                        quickSuggestionsDelay: 300,
                    }}
                />
                <div className="flex justify-between items-center text-sm text-muted">
                    <div className="flex items-center gap-2">
                        <span>{source.length} characters</span>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            loading={hogTestResultsLoading}
                            disabled={!source.trim()}
                            onClick={testHogOnSample}
                            data-attr="llma-evaluation-test-hog"
                        >
                            Test on sample
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Expected output:</span>
                        <LemonTag type="completion">Boolean (true/false)</LemonTag>
                    </div>
                </div>
            </div>

            <HogTestResultsPanel />

            <div className="bg-bg-light border rounded p-3">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold m-0">Examples</h4>
                </div>
                <div className="flex flex-wrap gap-1.5 mb-3">
                    {HOG_EXAMPLES.map((example) => (
                        <LemonButton
                            key={example.label}
                            type="secondary"
                            size="xsmall"
                            onClick={() => setHogSource(example.source)}
                        >
                            {example.label}
                        </LemonButton>
                    ))}
                </div>
                <h4 className="text-sm font-semibold mb-2">Available globals</h4>
                <div className="text-sm text-muted space-y-1">
                    <div>
                        <code>input</code> — the input to the LLM (prompt / messages)
                    </div>
                    <div>
                        <code>output</code> — the output from the LLM (response / choices)
                    </div>
                    <div>
                        <code>properties</code> — all event properties (e.g. <code>properties.$ai_model</code>)
                    </div>
                    <div>
                        <code>event.uuid</code>, <code>event.event</code>, <code>event.distinct_id</code>
                    </div>
                </div>
                <h4 className="text-sm font-semibold mt-3 mb-2">Tips</h4>
                <ul className="text-sm text-muted space-y-1 list-disc list-inside">
                    <li>
                        Return <code>true</code> (pass) or <code>false</code> (fail)
                    </li>
                    <li>
                        Use <code>print()</code> to add reasoning (visible in evaluation runs)
                    </li>
                    <li>Deterministic — runs instantly with no LLM cost</li>
                </ul>
            </div>
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { IconCheck, IconExternal, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { urls } from '~/scenes/urls'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { HogTestResult } from '../types'

const HOG_EXAMPLES: { label: string; source: string }[] = [
    {
        label: 'Quickstart',
        source: `// Explore the globals available to your evaluation
// input: the LLM input (string or array of messages)
// output: the LLM output (string or array of choices)
// properties: all event properties (e.g. properties.$ai_model)

print('--- input ---')
print(input)

print('--- output ---')
print(output)

print('--- model ---')
print(properties.$ai_model)

// Return true (pass) or false (fail)
return true`,
    },
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
        label: 'Contains keywords',
        source: `// Check that the output contains all expected keywords
let keywords := ['hello', 'world']
let missing := []
for (let i, kw in keywords) {
    if (not (output ilike concat('%', kw, '%'))) {
        missing := arrayPushBack(missing, kw)
    }
}
if (length(missing) > 0) {
    print('Missing keywords:', missing)
    return false
}
return true`,
    },
    {
        label: 'Print messages',
        source: `// Print each message and always pass
let messages := input
if (typeof(messages) == 'string' and startsWith(trim(messages), '[')) {
    messages := jsonParse(messages)
}
if (typeof(messages) == 'array') {
    for (let i, msg in messages) {
        print(concat('Message ', toString(i), ': [', msg.role, '] ', msg.content))
    }
} else {
    print('Input:', input)
}
return true`,
    },
    {
        label: 'Conversation length',
        source: `// Check that the conversation isn't too long
let max_turns := 10
let messages := input
if (typeof(messages) == 'string' and startsWith(trim(messages), '[')) {
    messages := jsonParse(messages)
}
if (typeof(messages) != 'array') {
    print('Input is not a message array, skipping')
    return true
}
let turns := length(messages)
print(concat(toString(turns), ' turns in conversation'))
if (turns > max_turns) {
    print(concat('Exceeds limit of ', toString(max_turns), ' turns'))
    return false
}
return true`,
    },
    {
        label: 'Error detection',
        source: `// Detect error patterns in the output and show the matching line
let patterns := [
    'error', 'exception', 'traceback',
    'failed', 'fatal', 'panic'
]
let lines := splitByString('\\n', output)
let found := []
for (let i, line in lines) {
    for (let j, pattern in patterns) {
        if (line ilike concat('%', pattern, '%') and not has(found, pattern)) {
            found := arrayPushBack(found, pattern)
            let trimmed := trim(line)
            if (length(trimmed) > 120) {
                trimmed := concat(substring(trimmed, 1, 120), '...')
            }
            print(concat('Found "', pattern, '": ', trimmed))
        }
    }
}
if (length(found) > 0) {
    return false
}
return true`,
    },
    {
        label: 'Output quality',
        source: `// Rate output quality based on length
let len := length(output)

if (len == 0) {
    print('Empty response')
    return false
} else if (len < 50) {
    print('Response too short:', len, 'chars')
    return false
} else if (len > 10000) {
    print('Response suspiciously long:', len, 'chars')
    return false
} else {
    print('Response length OK:', len, 'chars')
    return true
}`,
    },
    {
        label: 'Tools called',
        source: `// Check that specific tools were called in the output
let expected := ['get_weather', 'get_news']
let found := []
let missing := []
for (let i, tool in expected) {
    if (output ilike concat('%', tool, '%')) {
        found := arrayPushBack(found, tool)
    } else {
        missing := arrayPushBack(missing, tool)
    }
}
print('Found:', found)
if (length(missing) > 0) {
    print('Missing:', missing)
    return false
}
return true`,
    },
    {
        label: 'Regex safety checks',
        source: `// Run multiple regex safety checks and show matches
let checks := [
    ['No emails', '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+[.][a-zA-Z]{2,}'],
    ['No URLs', 'https?://[a-zA-Z0-9.-]+[.][a-zA-Z]{2,}'],
    ['No phone numbers', '[0-9]{3}[-. ][0-9]{3}[-. ][0-9]{4}'],
    ['No credit cards', '[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}']
]
let failed := []
for (let i, check in checks) {
    if (output =~ check.2) {
        failed := arrayPushBack(failed, check.1)
        let words := splitByString(' ', output)
        for (let j, word in words) {
            if (match(word, check.2)) {
                print(concat('  ', check.1, ': found "', word, '"'))
            }
        }
    }
}
if (length(failed) > 0) {
    print(concat('Failed ', toString(length(failed)), ' of ', toString(length(checks)), ' checks'))
    return false
}
print('All', length(checks), 'checks passed')
return true`,
    },
    {
        label: 'Cost & latency guard',
        source: `// Check that cost and latency are within budget
let max_cost := 0.05
let max_latency := 10

let cost := properties.$ai_total_cost_usd
let latency := properties.$ai_latency

if (cost > max_cost) {
    print(concat('Cost $', toString(cost), ' exceeds budget $', toString(max_cost)))
    return false
}
if (latency > max_latency) {
    print(concat('Latency ', toString(latency), 's exceeds limit ', toString(max_latency), 's'))
    return false
}
print(concat('OK — cost: $', toString(cost), ', latency: ', toString(latency), 's'))
return true`,
    },
    {
        label: 'Refusal detection',
        source: `// Detect when the model refuses to answer
let phrases := [
    'I cannot', 'I can\\'t', 'I\\'m unable',
    'I am unable', 'I\\'m sorry, but I',
    'I must decline', 'I\\'m not able'
]
for (let i, phrase in phrases) {
    if (output ilike concat('%', phrase, '%')) {
        print(concat('Refusal detected: "', phrase, '"'))
        return false
    }
}
return true`,
    },
    {
        label: 'Input relevance',
        source: `// Check that key terms from the input appear in the output
let words := splitByString(' ', input)
let key_terms := []
for (let i, word in words) {
    if (length(word) >= 5) {
        key_terms := arrayPushBack(key_terms, word)
    }
}
if (length(key_terms) == 0) {
    print('No key terms found in input (words >= 5 chars)')
    return true
}
let found := 0
let missing := []
for (let i, term in key_terms) {
    if (output ilike concat('%', term, '%')) {
        found := found + 1
    } else {
        missing := arrayPushBack(missing, term)
    }
}
let ratio := found / length(key_terms)
print(concat(toString(found), '/', toString(length(key_terms)), ' key terms found'))
if (length(missing) > 0) {
    print('Missing:', missing)
}
if (ratio < 0.3) {
    print('Output may not be relevant to the input')
    return false
}
return true`,
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
                        title: 'Reasoning',
                        key: 'reasoning',
                        render: (_, row) => (
                            <div className="truncate text-sm">
                                {row.reasoning || row.error || <span className="text-muted italic">none</span>}
                            </div>
                        ),
                    },
                    {
                        title: '',
                        key: 'link',
                        width: 32,
                        render: (_, row) =>
                            row.trace_id ? (
                                <Tooltip title="View generation">
                                    <Link
                                        to={urls.llmAnalyticsTrace(row.trace_id, {
                                            event: row.event_uuid,
                                        })}
                                        target="_blank"
                                    >
                                        <IconExternal className="text-muted text-base" />
                                    </Link>
                                </Tooltip>
                            ) : null,
                    },
                ]}
                expandable={{
                    expandedRowRender: (row) => (
                        <pre className="text-sm whitespace-pre-wrap m-0 p-2">
                            {row.reasoning || row.error || 'No output'}
                        </pre>
                    ),
                    rowExpandable: (row) => !!(row.reasoning || row.error),
                }}
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
                        <Tooltip title="Compile and run your code against up to 5 recent generations matching your trigger filters">
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
                        </Tooltip>
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
                    <div>
                        <h4 className="text-sm font-semibold m-0">Examples</h4>
                        <p className="text-xs text-muted m-0">Starter examples to play with</p>
                    </div>
                    <Link to="https://posthog.com/docs/hog" target="_blank" className="text-sm">
                        Hog language reference <IconExternal className="inline text-xs" />
                    </Link>
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
                        <code>properties</code> — all event properties (e.g. <code>properties.$ai_model</code>,{' '}
                        <code>properties.$ai_total_cost_usd</code> etc)
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
                </ul>
            </div>
        </div>
    )
}

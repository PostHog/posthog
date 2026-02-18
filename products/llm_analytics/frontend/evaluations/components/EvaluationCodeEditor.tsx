import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

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

export function EvaluationCodeEditor(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setHogSource } = useActions(llmEvaluationLogic)

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
                    <div>{source.length} characters</div>
                    <div className="flex items-center gap-2">
                        <span>Expected output:</span>
                        <LemonTag type="completion">Boolean (true/false)</LemonTag>
                    </div>
                </div>
            </div>

            <div className="bg-bg-light border rounded p-3">
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

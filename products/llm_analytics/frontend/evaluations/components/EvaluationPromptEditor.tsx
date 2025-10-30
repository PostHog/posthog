import { useActions, useValues } from 'kea'
import { Field } from 'kea-forms'

import { LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

export function EvaluationPromptEditor(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationPrompt } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return <div>Loading...</div>
    }

    const prompt = evaluation.evaluation_config.prompt

    return (
        <div className="space-y-4">
            <Field name="prompt" label="Evaluation prompt">
                <div className="space-y-2">
                    <LemonTextArea
                        value={prompt}
                        onChange={setEvaluationPrompt}
                        placeholder="Write a prompt that evaluates the LLM generation and returns true or false.

Example: Is this response helpful and accurate? Return true if yes, false if no."
                        rows={4}
                        className="font-mono text-sm"
                        maxLength={2000}
                    />
                    <div className="flex justify-between items-center text-sm text-muted">
                        <div>{prompt.length}/2000 characters</div>
                        <div className="flex items-center gap-2">
                            <span>Expected output:</span>
                            <LemonTag type="completion">Boolean (true/false)</LemonTag>
                        </div>
                    </div>
                </div>
            </Field>

            {prompt.length > 0 && (
                <div className="bg-bg-light border rounded p-3">
                    <h4 className="text-sm font-semibold mb-2">Prompt guidelines:</h4>
                    <ul className="text-sm text-muted space-y-1 list-disc list-inside">
                        <li>Be specific about what you want to evaluate</li>
                        <li>
                            Clearly instruct to return <code>true</code> or <code>false</code>
                        </li>
                        <li>Consider the context: input prompt, model output</li>
                        <li>Keep it concise but comprehensive</li>
                    </ul>
                </div>
            )}
        </div>
    )
}

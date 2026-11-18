import { LemonTextArea } from '@posthog/lemon-ui'

export function WorkflowTestVariables({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonTextArea
                value={value}
                onChange={onChange}
                minRows={3}
                placeholder='{"name": "Alex"}'
                data-attr="workflow-test-variables"
                className="font-mono ph-no-capture"
                aria-label="Test variables"
            />
            <span className="text-xs text-muted">
                Override variables for this test. To test steps after an AI task, paste its output into the variable
                those steps use. These values are not saved to the workflow.
            </span>
        </div>
    )
}

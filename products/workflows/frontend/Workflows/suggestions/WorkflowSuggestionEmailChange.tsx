import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import type { SuggestedFieldChange } from './suggestionChanges'
import { WorkflowSuggestionEmailCompareModal } from './WorkflowSuggestionEmailCompareModal'
import { WorkflowSuggestionFieldDiff } from './WorkflowSuggestionFieldDiff'

function asHtml(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value : null
}

export function WorkflowSuggestionEmailChange({
    change,
    isNewStep,
}: {
    change: SuggestedFieldChange
    isNewStep: boolean
}): JSX.Element {
    const [comparing, setComparing] = useState(false)

    return (
        <>
            <WorkflowSuggestionFieldDiff
                change={change}
                action={
                    <LemonButton
                        type="secondary"
                        size="small"
                        data-attr="workflow-suggestion-compare-emails"
                        onClick={() => setComparing(true)}
                    >
                        Compare emails
                    </LemonButton>
                }
            />
            <WorkflowSuggestionEmailCompareModal
                isOpen={comparing}
                onClose={() => setComparing(false)}
                isNewEmail={isNewStep}
                before={asHtml(change.before)}
                after={asHtml(change.after)}
            />
        </>
    )
}

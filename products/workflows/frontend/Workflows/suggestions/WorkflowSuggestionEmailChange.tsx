import { useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import type { SuggestedFieldChange } from './suggestionChanges'
import { condenseEmailTextDiff, diffEmailText, emailVisibleText } from './suggestionEmailText'
import { WorkflowSuggestionEmailCompareModal } from './WorkflowSuggestionEmailCompareModal'

function asHtml(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value : null
}

export function WorkflowSuggestionEmailChange({ change }: { change: SuggestedFieldChange }): JSX.Element {
    const [comparing, setComparing] = useState(false)
    const before = asHtml(change.before)
    const after = asHtml(change.after)

    const summary = useMemo(() => {
        const parts = diffEmailText(before ? emailVisibleText(before) : '', after ? emailVisibleText(after) : '')
        return parts.every((part) => part.kind === 'same') ? null : condenseEmailTextDiff(parts)
    }, [before, after])

    return (
        <div className="flex flex-col gap-2 rounded border p-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="font-medium">Email content</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="workflow-suggestion-compare-emails"
                    onClick={() => setComparing(true)}
                >
                    Compare emails
                </LemonButton>
            </div>
            {summary ? (
                <p className="mb-0 break-words" data-attr="workflow-suggestion-email-text-diff">
                    {summary
                        .map((part, index) =>
                            part.kind === 'gap' ? (
                                <span key={index} className="text-secondary">
                                    {' … '}
                                </span>
                            ) : part.kind === 'removed' ? (
                                <del key={index} className="bg-fill-error-highlight rounded px-0.5">
                                    {part.text}
                                </del>
                            ) : part.kind === 'added' ? (
                                <ins key={index} className="bg-fill-success-highlight rounded px-0.5 no-underline">
                                    {part.text}
                                </ins>
                            ) : (
                                <span key={index}>{part.text}</span>
                            )
                        )
                        .reduce<React.ReactNode[]>(
                            (nodes, node, index) => (index ? [...nodes, ' ', node] : [node]),
                            []
                        )}
                </p>
            ) : (
                <span className="text-secondary">
                    The text people read stays the same. Only the layout or styling changes.
                </span>
            )}
            <WorkflowSuggestionEmailCompareModal
                isOpen={comparing}
                onClose={() => setComparing(false)}
                before={before}
                after={after}
            />
        </div>
    )
}

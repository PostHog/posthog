import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { SourceFilterCatalogFieldApi } from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterSnippet, snippetsForField } from './sourceFilterSnippets'

export interface SourceFilterFieldSnippetsProps {
    field: SourceFilterCatalogFieldApi
    onInsert: (snippet: SourceFilterSnippet) => void
    disabledReason?: string
}

/** The selected field's description and the conditions it can take, ready to insert. */
export function SourceFilterFieldSnippets({
    field,
    onInsert,
    disabledReason,
}: SourceFilterFieldSnippetsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 rounded border border-primary bg-surface-secondary p-2">
            <span className="text-xs text-secondary">{field.description}</span>
            <div className="flex flex-wrap gap-1">
                {snippetsForField(field).map((snippet) => (
                    <LemonButton
                        key={snippet.text}
                        type="secondary"
                        size="xsmall"
                        icon={<IconPlus />}
                        onClick={() => onInsert(snippet)}
                        disabledReason={disabledReason}
                        aria-label={`Add ${snippet.text}`}
                        data-attr="signal-source-filter-snippet"
                    >
                        <span className="font-mono">{snippet.text}</span>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}

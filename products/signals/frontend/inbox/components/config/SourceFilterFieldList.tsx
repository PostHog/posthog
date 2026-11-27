import { LemonButton } from '@posthog/lemon-ui'

import type { SourceFilterCatalogFieldApi } from 'products/signals/frontend/generated/api.schemas'

export interface SourceFilterFieldListProps {
    fields: SourceFilterCatalogFieldApi[]
    selectedFieldName: string | null
    onSelect: (name: string) => void
}

export function SourceFilterFieldList({
    fields,
    selectedFieldName,
    onSelect,
}: SourceFilterFieldListProps): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5" role="group" aria-label="Fields">
            <span className="text-xs font-semibold text-default">Fields</span>
            {fields.map((field) => (
                <LemonButton
                    key={field.name}
                    size="xsmall"
                    fullWidth
                    active={field.name === selectedFieldName}
                    onClick={() => onSelect(field.name)}
                    sideIcon={<span className="text-xxs text-muted">{field.type}</span>}
                    data-attr="signal-source-filter-field"
                >
                    <span className="truncate font-mono">{field.name}</span>
                </LemonButton>
            ))}
        </div>
    )
}

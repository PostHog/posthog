import { ReactNode } from 'react'

import { WarehouseSuggestionApi } from '../generated/api.schemas'
import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { CertificationSuggestionRowProps } from './CertificationSuggestionRow'
import { QuillCertificationSuggestionRow } from './QuillCertificationSuggestionRow'
import { QuillMaterializeSuggestionRow } from './QuillMaterializeSuggestionRow'
import { QuillSuggestedModelsSection } from './QuillSuggestedModelsSection'
import { QuillRowSelectionProps } from './QuillSuggestionRow'
import { QuillUnmaterializeSuggestionRow } from './QuillUnmaterializeSuggestionRow'
import { SuggestedModelsGroupsProps } from './SuggestedModelsGroups'

const ROW_FOR_KIND: Record<
    string,
    (props: CertificationSuggestionRowProps & QuillRowSelectionProps) => JSX.Element | null
> = {
    materialize: QuillMaterializeSuggestionRow,
    unmaterialize: QuillUnmaterializeSuggestionRow,
    certify: QuillCertificationSuggestionRow,
    deprecate: QuillCertificationSuggestionRow,
}

export interface QuillSuggestedModelsGroupsProps extends SuggestedModelsGroupsProps {
    renderSelection?: (suggestion: WarehouseSuggestionApi) => ReactNode
}

export function QuillSuggestedModelsGroups({
    groups,
    windowDays,
    renderSelection,
}: QuillSuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map(({ kind, suggestions }) => (
                <QuillSuggestedModelsSection key={kind} {...SUGGESTED_MODEL_SECTIONS[kind]}>
                    {suggestions.map((suggestion) => {
                        const RowComponent = ROW_FOR_KIND[kind] ?? QuillMaterializeSuggestionRow
                        return (
                            <RowComponent
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                                selection={renderSelection?.(suggestion)}
                            />
                        )
                    })}
                </QuillSuggestedModelsSection>
            ))}
        </>
    )
}

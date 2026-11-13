import { ReactNode } from 'react'

import { WarehouseSuggestionApi } from '../generated/api.schemas'
import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { SuggestionGroup } from '../warehouseSuggestionsLogic'
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
    renderGroupSelection?: (group: SuggestionGroup) => ReactNode
}

export function QuillSuggestedModelsGroups({
    groups,
    windowDays,
    renderSelection,
    renderGroupSelection,
}: QuillSuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map((group) => (
                <QuillSuggestedModelsSection
                    key={group.kind}
                    {...SUGGESTED_MODEL_SECTIONS[group.kind]}
                    selection={renderGroupSelection?.(group)}
                >
                    {group.suggestions.map((suggestion) => {
                        const RowComponent = ROW_FOR_KIND[group.kind] ?? QuillMaterializeSuggestionRow
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

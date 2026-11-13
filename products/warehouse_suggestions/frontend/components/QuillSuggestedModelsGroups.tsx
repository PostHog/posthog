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
    assigneeColumn?: boolean
}

export function QuillSuggestedModelsGroups({
    groups,
    windowDays,
    renderSelection,
    renderGroupSelection,
    assigneeColumn,
}: QuillSuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map((group, index) => (
                <QuillSuggestedModelsSection
                    key={group.kind}
                    {...SUGGESTED_MODEL_SECTIONS[group.kind]}
                    selection={renderGroupSelection?.(group)}
                    assigneeColumn={assigneeColumn}
                    showsAssigneeLabel={index === 0}
                >
                    {group.suggestions.map((suggestion) => {
                        const RowComponent = ROW_FOR_KIND[group.kind] ?? QuillMaterializeSuggestionRow
                        return (
                            <RowComponent
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                                selection={renderSelection?.(suggestion)}
                                assigneeColumn={assigneeColumn}
                            />
                        )
                    })}
                </QuillSuggestedModelsSection>
            ))}
        </>
    )
}

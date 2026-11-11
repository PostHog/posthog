import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { CertificationSuggestionRowProps } from './CertificationSuggestionRow'
import { QuillCertificationSuggestionRow } from './QuillCertificationSuggestionRow'
import { QuillMaterializeSuggestionRow } from './QuillMaterializeSuggestionRow'
import { QuillSuggestedModelsSection } from './QuillSuggestedModelsSection'
import { QuillUnmaterializeSuggestionRow } from './QuillUnmaterializeSuggestionRow'
import { SuggestedModelsGroupsProps } from './SuggestedModelsGroups'

const ROW_FOR_KIND: Record<string, (props: CertificationSuggestionRowProps) => JSX.Element | null> = {
    materialize: QuillMaterializeSuggestionRow,
    unmaterialize: QuillUnmaterializeSuggestionRow,
    deprecate: QuillCertificationSuggestionRow,
}

export function QuillSuggestedModelsGroups({ groups, windowDays }: SuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map(({ kind, suggestions }) => (
                <QuillSuggestedModelsSection key={kind} {...SUGGESTED_MODEL_SECTIONS[kind]}>
                    {suggestions.map((suggestion) => {
                        const RowComponent = ROW_FOR_KIND[kind] ?? QuillMaterializeSuggestionRow
                        return <RowComponent key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                    })}
                </QuillSuggestedModelsSection>
            ))}
        </>
    )
}

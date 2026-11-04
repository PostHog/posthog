import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { QuillMaterializeSuggestionRow } from './QuillMaterializeSuggestionRow'
import { QuillSuggestedModelsSection } from './QuillSuggestedModelsSection'
import { QuillUnmaterializeSuggestionRow } from './QuillUnmaterializeSuggestionRow'
import { SuggestedModelsGroupsProps } from './SuggestedModelsGroups'

export function QuillSuggestedModelsGroups({ groups, windowDays }: SuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map(({ kind, suggestions }) => (
                <QuillSuggestedModelsSection key={kind} {...SUGGESTED_MODEL_SECTIONS[kind]}>
                    {suggestions.map((suggestion) =>
                        kind === 'unmaterialize' ? (
                            <QuillUnmaterializeSuggestionRow
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                            />
                        ) : (
                            <QuillMaterializeSuggestionRow
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                            />
                        )
                    )}
                </QuillSuggestedModelsSection>
            ))}
        </>
    )
}

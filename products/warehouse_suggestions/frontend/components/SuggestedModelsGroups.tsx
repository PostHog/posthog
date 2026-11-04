import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { SuggestionGroup } from '../warehouseSuggestionsLogic'
import { MaterializeSuggestionRow } from './MaterializeSuggestionRow'
import { SuggestedModelsSection } from './SuggestedModelsSection'
import { UnmaterializeSuggestionRow } from './UnmaterializeSuggestionRow'

export interface SuggestedModelsGroupsProps {
    groups: SuggestionGroup[]
    windowDays: number
}

export function SuggestedModelsGroups({ groups, windowDays }: SuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map(({ kind, suggestions }) => (
                <SuggestedModelsSection key={kind} {...SUGGESTED_MODEL_SECTIONS[kind]}>
                    {suggestions.map((suggestion) =>
                        kind === 'unmaterialize' ? (
                            <UnmaterializeSuggestionRow
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                            />
                        ) : (
                            <MaterializeSuggestionRow
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                            />
                        )
                    )}
                </SuggestedModelsSection>
            ))}
        </>
    )
}

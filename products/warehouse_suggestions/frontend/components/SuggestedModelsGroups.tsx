import { WarehouseSuggestionApi } from '../generated/api.schemas'
import { SUGGESTED_MODEL_SECTIONS } from '../suggestionCopy'
import { SuggestionGroup } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRow } from './CertificationSuggestionRow'
import { MaterializeSuggestionRow } from './MaterializeSuggestionRow'
import { SuggestedModelsSection } from './SuggestedModelsSection'
import { UnmaterializeSuggestionRow } from './UnmaterializeSuggestionRow'

const ROW_FOR_KIND: Record<
    string,
    (props: { suggestion: WarehouseSuggestionApi; windowDays: number }) => JSX.Element | null
> = {
    materialize: MaterializeSuggestionRow,
    unmaterialize: UnmaterializeSuggestionRow,
    deprecate: CertificationSuggestionRow,
}

export interface SuggestedModelsGroupsProps {
    groups: SuggestionGroup[]
    windowDays: number
}

export function SuggestedModelsGroups({ groups, windowDays }: SuggestedModelsGroupsProps): JSX.Element {
    return (
        <>
            {groups.map(({ kind, suggestions }) => (
                <SuggestedModelsSection key={kind} {...SUGGESTED_MODEL_SECTIONS[kind]}>
                    {suggestions.map((suggestion) => {
                        const RowComponent = ROW_FOR_KIND[kind] ?? MaterializeSuggestionRow
                        return <RowComponent key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                    })}
                </SuggestedModelsSection>
            ))}
        </>
    )
}

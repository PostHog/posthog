import type { AIEnrichmentSource } from './aiEnrichmentLogic'
import type { AIEnrichmentOutputField } from './aiEnrichmentOutputFields'

export function sourcesDisabledReason(
    sources: AIEnrichmentSource[],
    outputFields: AIEnrichmentOutputField[]
): string | undefined {
    const keys = new Set<string>()
    for (const source of sources) {
        if (!source.key.trim()) {
            return 'Add a key for every web source'
        }
        if (keys.has(source.key)) {
            return 'Web source keys must be unique'
        }
        keys.add(source.key)
        if (source.kind === 'fetch' && !source.url?.trim()) {
            return 'Add a URL for every fetch source'
        }
        if (source.kind === 'search' && !source.query?.trim()) {
            return 'Add a query for every search source'
        }
    }
    if (sources.length === 0) {
        return undefined
    }
    const hasEvidenceUrlField = outputFields.some((field) => field.key === 'evidence_url' && field.type === 'string')
    if (!hasEvidenceUrlField) {
        return "Add a string 'evidence_url' output field to use web sources"
    }
    return undefined
}

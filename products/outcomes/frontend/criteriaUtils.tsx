import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { OutcomeAtomApi, OutcomeCriteriaApi, OutcomePathApi } from './generated/api.schemas'

export interface OutcomeEvidenceAtom {
    event: string
    aggregation: string
    aggregation_property: string | null
    threshold: number
    attained: number
    satisfied: boolean
}

export interface OutcomeEvidence {
    winning_path: number
    paths: { satisfied: boolean; min_matches: number; atoms: OutcomeEvidenceAtom[] }[]
}

export function emptyAtom(): OutcomeAtomApi {
    return { event: '', properties: [], aggregation: 'count', aggregation_property: null, threshold: 1 }
}

export function emptyCriteria(): OutcomeCriteriaApi {
    return { paths: [{ atoms: [emptyAtom()], min_matches: null }] }
}

export function atomIsComplete(atom: OutcomeAtomApi): boolean {
    if (!atom.event) {
        return false
    }
    if (atom.aggregation !== 'count' && !atom.aggregation_property) {
        return false
    }
    return (atom.threshold ?? 0) > 0
}

export function criteriaAreComplete(criteria: OutcomeCriteriaApi): boolean {
    return criteria.paths.length > 0 && criteria.paths.every((path) => path.atoms.every(atomIsComplete))
}

function formatNumber(value: number): string {
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100)
}

function describeAggregation(atom: OutcomeAtomApi): string {
    if (atom.aggregation === 'sum') {
        return `sum of ${atom.aggregation_property}`
    }
    if (atom.aggregation === 'distinct') {
        return `distinct ${atom.aggregation_property}`
    }
    return 'count'
}

export function describeAtom(atom: OutcomeAtomApi): string {
    const filters = atom.properties?.length ? ` (${atom.properties.length} filters)` : ''
    const aggregation = atom.aggregation === 'count' ? '' : ` ${describeAggregation(atom)}`
    return `${atom.event}${filters}${aggregation} ≥ ${formatNumber(atom.threshold ?? 1)}`
}

export function describePath(path: OutcomePathApi): string {
    const prefix = path.min_matches && path.min_matches < path.atoms.length ? `at least ${path.min_matches} of: ` : ''
    return prefix + path.atoms.map(describeAtom).join(' AND ')
}

export function describeCriteria(criteria: OutcomeCriteriaApi): string {
    return criteria.paths.map(describePath).join('  OR  ')
}

export function describeEvidenceProgress(evidence: OutcomeEvidence): string {
    const winning = evidence.paths[evidence.winning_path]
    if (!winning) {
        return ''
    }
    return winning.atoms.map((atom) => `${formatNumber(atom.attained)}/${formatNumber(atom.threshold)}`).join(' · ')
}

export function CriteriaSummary({ criteria }: { criteria: OutcomeCriteriaApi }): JSX.Element {
    return (
        <div className="deprecated-space-y-1">
            {criteria.paths.map((path, pathIndex) => (
                <div key={pathIndex} className="flex items-baseline gap-1 flex-wrap">
                    {pathIndex > 0 && <span className="text-muted text-xs font-semibold">OR</span>}
                    {path.min_matches && path.min_matches < path.atoms.length ? (
                        <span className="text-muted text-xs">at least {path.min_matches} of:</span>
                    ) : null}
                    {path.atoms.map((atom, atomIndex) => (
                        <span key={atomIndex} className="whitespace-nowrap">
                            {atomIndex > 0 && <span className="text-muted text-xs font-semibold"> AND </span>}
                            <PropertyKeyInfo value={atom.event} type={TaxonomicFilterGroupType.Events} disablePopover />
                            {atom.properties?.length ? (
                                <span className="text-muted"> ({atom.properties.length} filters)</span>
                            ) : null}
                            {atom.aggregation !== 'count' && (
                                <span className="text-muted"> {describeAggregation(atom)}</span>
                            )}{' '}
                            &ge; {formatNumber(atom.threshold ?? 1)}
                        </span>
                    ))}
                </div>
            ))}
        </div>
    )
}

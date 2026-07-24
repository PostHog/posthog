import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import type { AnyPropertyFilter } from '~/types'

import { emptyAtom } from './criteriaUtils'
import type { OutcomeAtomApi, OutcomeCriteriaApi } from './generated/api.schemas'

export interface CriteriaBuilderProps {
    value: OutcomeCriteriaApi
    onChange: (criteria: OutcomeCriteriaApi) => void
}

function updateIndex<T>(items: T[], index: number, replacement: T): T[] {
    return items.map((item, i) => (i === index ? replacement : item))
}

function AtomEditor({
    atom,
    pathIndex,
    atomIndex,
    removable,
    onChange,
    onRemove,
}: {
    atom: OutcomeAtomApi
    pathIndex: number
    atomIndex: number
    removable: boolean
    onChange: (atom: OutcomeAtomApi) => void
    onRemove: () => void
}): JSX.Element {
    const eventNames = atom.event ? [atom.event] : []
    return (
        <div className="border rounded p-2 deprecated-space-y-2 bg-surface-secondary">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonSelect
                    size="small"
                    value={atom.aggregation ?? 'count'}
                    onChange={(aggregation) =>
                        onChange({
                            ...atom,
                            aggregation,
                            aggregation_property: aggregation === 'count' ? null : atom.aggregation_property,
                        })
                    }
                    options={[
                        { value: 'count' as const, label: 'Count of' },
                        { value: 'sum' as const, label: 'Sum of' },
                        { value: 'distinct' as const, label: 'Distinct values of' },
                    ]}
                    data-attr={`outcome-atom-aggregation-${pathIndex}-${atomIndex}`}
                />
                {atom.aggregation !== 'count' && (
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        value={atom.aggregation_property ?? ''}
                        onChange={(value) => onChange({ ...atom, aggregation_property: value ? String(value) : null })}
                        eventNames={eventNames}
                        type="secondary"
                        size="small"
                        placeholder="Select a property"
                        data-attr={`outcome-atom-property-${pathIndex}-${atomIndex}`}
                        renderValue={(value) =>
                            value ? (
                                <PropertyKeyInfo
                                    value={String(value)}
                                    disablePopover
                                    type={TaxonomicFilterGroupType.EventProperties}
                                />
                            ) : null
                        }
                    />
                )}
                <span className="text-muted">{atom.aggregation === 'count' ? '' : 'on'}</span>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.Events}
                    value={atom.event}
                    onChange={(value) => onChange({ ...atom, event: value ? String(value) : '' })}
                    type="secondary"
                    size="small"
                    placeholder="Select an event"
                    data-attr={`outcome-atom-event-${pathIndex}-${atomIndex}`}
                    renderValue={(value) =>
                        value ? (
                            <PropertyKeyInfo
                                value={String(value)}
                                disablePopover
                                type={TaxonomicFilterGroupType.Events}
                            />
                        ) : null
                    }
                    excludedProperties={{ events: [null] }}
                    selectingKeyOnly
                />
                <span className="text-muted">&ge;</span>
                <LemonInput
                    type="number"
                    size="small"
                    className="w-24"
                    min={atom.aggregation === 'sum' ? 0.01 : 1}
                    step={atom.aggregation === 'sum' ? 0.01 : 1}
                    value={atom.threshold ?? 1}
                    onChange={(value) => onChange({ ...atom, threshold: value ?? 1 })}
                    data-attr={`outcome-atom-threshold-${pathIndex}-${atomIndex}`}
                />
                {removable && (
                    <LemonButton
                        size="small"
                        icon={<IconTrash />}
                        onClick={onRemove}
                        tooltip="Remove condition"
                        data-attr={`outcome-atom-remove-${pathIndex}-${atomIndex}`}
                    />
                )}
            </div>
            <PropertyFilters
                propertyFilters={(atom.properties ?? []) as AnyPropertyFilter[]}
                onChange={(properties) => onChange({ ...atom, properties: properties as OutcomeAtomApi['properties'] })}
                pageKey={`outcome-atom-${pathIndex}-${atomIndex}`}
                eventNames={eventNames}
                buttonSize="small"
                addText="Add filter"
            />
        </div>
    )
}

export function CriteriaBuilder({ value, onChange }: CriteriaBuilderProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            {value.paths.map((path, pathIndex) => (
                <div key={pathIndex}>
                    {pathIndex > 0 && <div className="text-center text-muted text-xs font-semibold py-1">OR</div>}
                    <div className="border rounded p-3 deprecated-space-y-2">
                        <div className="flex items-center justify-between">
                            <span className="font-semibold">Path {pathIndex + 1}</span>
                            <div className="flex items-center gap-2">
                                {path.atoms.length > 1 && (
                                    <LemonSelect
                                        size="small"
                                        value={path.min_matches ?? null}
                                        onChange={(min_matches) =>
                                            onChange({
                                                ...value,
                                                paths: updateIndex(value.paths, pathIndex, { ...path, min_matches }),
                                            })
                                        }
                                        options={[
                                            { value: null, label: 'All conditions' },
                                            ...Array.from({ length: path.atoms.length - 1 }, (_, i) => ({
                                                value: i + 1,
                                                label: `At least ${i + 1} of ${path.atoms.length}`,
                                            })),
                                        ]}
                                        data-attr={`outcome-path-min-matches-${pathIndex}`}
                                    />
                                )}
                                {value.paths.length > 1 && (
                                    <LemonButton
                                        size="small"
                                        icon={<IconTrash />}
                                        tooltip="Remove path"
                                        onClick={() =>
                                            onChange({
                                                ...value,
                                                paths: value.paths.filter((_, i) => i !== pathIndex),
                                            })
                                        }
                                        data-attr={`outcome-path-remove-${pathIndex}`}
                                    />
                                )}
                            </div>
                        </div>
                        {path.atoms.map((atom, atomIndex) => (
                            <div key={atomIndex} className="deprecated-space-y-2">
                                {atomIndex > 0 && <div className="text-muted text-xs font-semibold">AND</div>}
                                <AtomEditor
                                    atom={atom}
                                    pathIndex={pathIndex}
                                    atomIndex={atomIndex}
                                    removable={path.atoms.length > 1}
                                    onChange={(nextAtom) =>
                                        onChange({
                                            ...value,
                                            paths: updateIndex(value.paths, pathIndex, {
                                                ...path,
                                                atoms: updateIndex(path.atoms, atomIndex, nextAtom),
                                            }),
                                        })
                                    }
                                    onRemove={() =>
                                        onChange({
                                            ...value,
                                            paths: updateIndex(value.paths, pathIndex, {
                                                ...path,
                                                atoms: path.atoms.filter((_, i) => i !== atomIndex),
                                                min_matches:
                                                    path.min_matches && path.min_matches >= path.atoms.length
                                                        ? null
                                                        : path.min_matches,
                                            }),
                                        })
                                    }
                                />
                            </div>
                        ))}
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() =>
                                onChange({
                                    ...value,
                                    paths: updateIndex(value.paths, pathIndex, {
                                        ...path,
                                        atoms: [...path.atoms, emptyAtom()],
                                    }),
                                })
                            }
                            data-attr={`outcome-path-add-atom-${pathIndex}`}
                        >
                            AND condition
                        </LemonButton>
                    </div>
                </div>
            ))}
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPlus />}
                onClick={() =>
                    onChange({ ...value, paths: [...value.paths, { atoms: [emptyAtom()], min_matches: null }] })
                }
                data-attr="outcome-add-path"
            >
                OR path
            </LemonButton>
        </div>
    )
}

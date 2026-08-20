import { useActions } from 'kea'
import { match } from 'ts-pattern'

import { Spinner } from '@posthog/lemon-ui'

import { BUILT_IN_ERROR_TRACKING_PROPERTIES } from '../builtInProperties'
import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY, issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { ExceptionPropertiesTable } from './ExceptionPropertiesTable'

export type ContextDisplayProps = {
    loading: boolean
    properties?: Record<string, unknown>
    additionalProperties: Record<string, unknown>
    propertyNameFilter?: string
}

export function ContextDisplay({
    loading,
    properties,
    additionalProperties,
    propertyNameFilter = '',
}: ContextDisplayProps): JSX.Element {
    const { addPropertyFilter } = useActions(issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }))
    const onFilterValue = (key: string, value: string | number | boolean): void => {
        addPropertyFilter(key, value)
    }
    const additionalEntries = Object.entries(additionalProperties)
        .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey, undefined, { sensitivity: 'base' }))
        .map(([key, value]) => ({
            key,
            value,
            filterKey: key,
        }))
    const builtInEntries = BUILT_IN_ERROR_TRACKING_PROPERTIES.map(({ property, title, versionProperty }) => ({
        key: title,
        value: getBuiltInPropertyValue(properties, property, versionProperty),
        filterKey: property,
        filterValue: properties?.[property],
    }))
    const normalizedPropertyNameFilter = propertyNameFilter.trim().toLocaleLowerCase()

    return (
        <>
            {match(loading)
                .with(true, () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with(false, () => (
                    <ExceptionPropertiesTable
                        sections={[
                            {
                                id: 'built-in-exception-properties',
                                title: 'Built-in properties',
                                entries: filterEntriesByPropertyName(builtInEntries, normalizedPropertyNameFilter),
                            },
                            {
                                id: 'custom-exception-properties',
                                title: 'Custom properties',
                                entries: filterEntriesByPropertyName(additionalEntries, normalizedPropertyNameFilter),
                            },
                        ]}
                        emptyMessage={normalizedPropertyNameFilter ? 'No matching properties' : 'No properties'}
                        onFilterValue={onFilterValue}
                    />
                ))
                .exhaustive()}
        </>
    )
}

function filterEntriesByPropertyName<T extends { key: string; filterKey?: string }>(
    entries: T[],
    normalizedPropertyNameFilter: string
): T[] {
    if (!normalizedPropertyNameFilter) {
        return entries
    }

    return entries.filter((entry) =>
        [entry.key, entry.filterKey]
            .filter((value): value is string => typeof value === 'string')
            .some((value) => value.toLocaleLowerCase().includes(normalizedPropertyNameFilter))
    )
}

function getBuiltInPropertyValue(
    properties: Record<string, unknown> | undefined,
    property: string,
    versionProperty: string | undefined
): unknown {
    const value = properties?.[property]
    if (!versionProperty) {
        return value
    }

    const version = properties?.[versionProperty]
    const parts = [value, version].filter((part) => part !== undefined && part !== null && part !== '')
    return parts.length > 0 ? parts.join(' ') : undefined
}

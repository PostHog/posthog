import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useMemo, useRef } from 'react'

import { IconBrackets, IconCheckCircle, IconFlag, IconPerson } from '@posthog/icons'

import { FilterPickerNode, FilterPickerToken } from 'lib/components/FilterPicker'
import {
    createPropertyFilterPickerNodes,
    createPropertyFilterToken,
    editPathForPropertyFilter,
    PropertyValueLoaderContext,
    PropertyValueLoaderResult,
} from 'lib/components/FilterPicker/adapters'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, PropertyFilterType, PropertyType, UniversalFiltersGroup } from '~/types'

import { AssigneeLabelDisplay } from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from 'products/error_tracking/frontend/components/Assignee/assigneeSelectLogic'
import {
    ErrorTrackingStatusFilter,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

const ERROR_TRACKING_EVENT_NAMES = ['$exception']

const STATUS_OPTIONS: { value: ErrorTrackingStatusFilter; label: string }[] = [
    { value: null, label: 'All issues' },
    { value: 'active', label: 'Active' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'suppressed', label: 'Suppressed' },
    { value: 'archived', label: 'Archived' },
]

const SECTIONS = {
    issue: { id: 'issue', label: 'Issue', icon: <IconCheckCircle /> },
    person: { id: 'person', label: 'Person', icon: <IconPerson /> },
    exception: { id: 'exception', label: 'Exception', icon: <IconBrackets /> },
    release: { id: 'release', label: 'Release', icon: <IconFlag /> },
}

const PROPERTY_LABELS: Record<string, string> = {
    first_seen: 'First seen',
    timestamp: 'Last seen',
    email: 'Email',
    $active_feature_flags: 'Feature flag',
    id: 'Cohort',
    $exception_types: 'Type',
    $exception_values: 'Message',
    $exception_sources: 'Source',
    $exception_functions: 'Function',
    $exception_releases: 'Name',
    $app_version: 'Version',
}

// Status and assignee aren't AnyPropertyFilters (they live in issueQueryOptionsLogic, not the filter group),
// so they can't go through createPropertyFilterToken. This keeps their token shape consistent with it.
function buildControlToken(options: {
    id: string
    property: ReactNode
    value: ReactNode
    title: string
    editNodeIds: string[]
    onRemove: () => void
}): FilterPickerToken {
    return {
        id: options.id,
        parts: [
            { kind: 'property', label: options.property },
            { kind: 'operator', label: '=' },
            { kind: 'value', label: options.value },
        ],
        title: options.title,
        editPath: { nodeIds: options.editNodeIds },
        removable: true,
        onRemove: options.onRemove,
    }
}

function useStatusNode(): { node: FilterPickerNode; token?: FilterPickerToken } {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)
    const statusLabel = STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status

    return useMemo(
        () => ({
            node: {
                id: 'issue:status',
                label: 'Status',
                section: SECTIONS.issue,
                kind: 'branch',
                searchPlaceholder: 'Search statuses…',
                getChildren: ({ query }) => ({
                    nodes: STATUS_OPTIONS.filter((option) =>
                        option.label.toLowerCase().includes(query.trim().toLowerCase())
                    ).map((option) => ({
                        id: `issue:status:value:${option.value ?? 'all'}`,
                        label: option.label,
                        kind: 'action',
                        onSelect: ({ close }) => {
                            setStatus(option.value)
                            close()
                        },
                    })),
                }),
            },
            token: status
                ? buildControlToken({
                      id: `status:${status}`,
                      property: 'Status',
                      value: statusLabel,
                      title: `Status = ${statusLabel}`,
                      editNodeIds: ['issue:status'],
                      onRemove: () => setStatus(null),
                  })
                : undefined,
        }),
        [setStatus, status, statusLabel]
    )
}

function useAssigneeNode(): { node: FilterPickerNode; token?: FilterPickerToken } {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)
    const { meFirstMembers, roles, loading, resolveAssignee } = useValues(assigneeSelectLogic)
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const resolvedAssignee = resolveAssignee(assignee ?? null)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return useMemo(
        () => ({
            node: {
                id: 'issue:assignee',
                label: 'Assignee',
                section: SECTIONS.issue,
                kind: 'branch',
                searchPlaceholder: 'Search assignees…',
                getChildren: ({ query }) => {
                    const trimmed = query.trim().toLowerCase()
                    const filteredRoles = roles.filter((role) => role.name.toLowerCase().includes(trimmed))
                    const filteredMembers = meFirstMembers.filter((member) => {
                        const name = member.user.first_name || member.user.email || String(member.user.id)
                        return name.toLowerCase().includes(trimmed)
                    })

                    return {
                        isLoading: loading && !filteredRoles.length && !filteredMembers.length,
                        nodes: [
                            {
                                id: 'issue:assignee:any',
                                label: 'Any assignee',
                                kind: 'action',
                                onSelect: ({ close }) => {
                                    setAssignee(null)
                                    close()
                                },
                            },
                            ...filteredRoles.map<FilterPickerNode>((role) => ({
                                id: `issue:assignee:role:${role.id}`,
                                label: role.name,
                                hint: 'Role',
                                kind: 'action',
                                onSelect: ({ close }) => {
                                    setAssignee({ type: 'role', id: role.id })
                                    close()
                                },
                            })),
                            ...filteredMembers.map<FilterPickerNode>((member) => ({
                                id: `issue:assignee:user:${member.user.id}`,
                                label: member.user.first_name || member.user.email || String(member.user.id),
                                hint: 'User',
                                kind: 'action',
                                onSelect: ({ close }) => {
                                    setAssignee({ type: 'user', id: member.user.id })
                                    close()
                                },
                            })),
                        ],
                    }
                },
            },
            token: assignee
                ? buildControlToken({
                      id: `assignee:${assignee.type}:${assignee.id}`,
                      property: 'Assignee',
                      value: <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />,
                      title: 'Assignee',
                      editNodeIds: ['issue:assignee'],
                      onRemove: () => setAssignee(null),
                  })
                : undefined,
        }),
        [assignee, loading, meFirstMembers, resolvedAssignee, roles, setAssignee]
    )
}

function useValueLoader(): (context: PropertyValueLoaderContext) => PropertyValueLoaderResult {
    const { options, formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const lastLoadedValueKeyRef = useRef<string | null>(null)

    return ({ property, query, eventNames }) => {
        if (property.type === PropertyFilterType.Cohort) {
            const trimmed = query.trim().toLowerCase()
            return {
                isLoading: cohortsLoading,
                values: cohorts.results
                    .filter((cohort) => (cohort.name ?? '').toLowerCase().includes(trimmed))
                    .map((cohort) => ({ value: cohort.id, label: cohort.name ?? String(cohort.id) })),
            }
        }

        const definitionType = propertyFilterTypeToPropertyDefinitionType(property.type)
        const trimmed = query.trim()
        const loadKey = `${definitionType}:${property.key}:${trimmed}:${eventNames?.join(',') ?? ''}`
        const values = options[property.key]?.values ?? []
        return {
            isLoading: options[property.key]?.status === 'loading' && !values.length,
            allowCustomValues: true,
            values: values
                .filter((value) => !trimmed || String(value.name).toLowerCase().includes(trimmed.toLowerCase()))
                .map((value) => ({
                    value: value.name,
                    label: String(formatPropertyValueForDisplay(property.key, value.name, definitionType)),
                })),
            // Called from FilterPicker's content effect (never during render), so dispatching here is safe.
            // The ref de-dupes repeat loads for the same property/query/event scope.
            load: () => {
                if (lastLoadedValueKeyRef.current === loadKey) {
                    return
                }
                lastLoadedValueKeyRef.current = loadKey
                loadPropertyValues({
                    endpoint: undefined,
                    type: definitionType,
                    newInput: trimmed || undefined,
                    propertyKey: property.key,
                    eventNames,
                })
            },
        }
    }
}

export function useErrorTrackingFilterPicker({
    filterGroup,
    onFilterChange,
}: {
    filterGroup: UniversalFiltersGroup
    onFilterChange: (group: UniversalFiltersGroup) => void
}): { pickerRootNodes: FilterPickerNode[]; pickerTokens: FilterPickerToken[] } {
    const status = useStatusNode()
    const assignee = useAssigneeNode()
    const valueLoader = useValueLoader()
    const setGroupValues = useCallback(
        (values: AnyPropertyFilter[]): void => onFilterChange({ ...filterGroup, values }),
        [filterGroup, onFilterChange]
    )
    // The picker only ever adds leaf property filters (never nested groups), so narrow the loosely-typed
    // group values to AnyPropertyFilter once here rather than casting at every use site.
    const filterValues = useMemo(() => filterGroup.values as AnyPropertyFilter[], [filterGroup.values])
    const { cohorts } = useValues(cohortsModel)

    const propertyNodes = useMemo(
        () =>
            createPropertyFilterPickerNodes({
                eventNames: ERROR_TRACKING_EVENT_NAMES,
                valueLoader,
                onSelect: (filter, { close }) => {
                    setGroupValues([...filterValues, filter])
                    close()
                },
                properties: [
                    {
                        key: 'first_seen',
                        label: 'First seen',
                        type: PropertyFilterType.ErrorTrackingIssue,
                        propertyType: PropertyType.DateTime,
                        section: SECTIONS.issue,
                    },
                    {
                        key: 'timestamp',
                        label: 'Last seen',
                        type: PropertyFilterType.EventMetadata,
                        propertyType: PropertyType.DateTime,
                        section: SECTIONS.issue,
                    },
                    {
                        key: 'email',
                        label: 'Email',
                        type: PropertyFilterType.Person,
                        propertyType: PropertyType.String,
                        section: SECTIONS.person,
                    },
                    {
                        key: '$active_feature_flags',
                        label: 'Feature flag',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.person,
                    },
                    {
                        key: 'id',
                        label: 'Cohort',
                        type: PropertyFilterType.Cohort,
                        propertyType: PropertyType.Cohort,
                        section: SECTIONS.person,
                    },
                    {
                        key: '$exception_types',
                        label: 'Type',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.exception,
                    },
                    {
                        key: '$exception_values',
                        label: 'Message',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.exception,
                    },
                    {
                        key: '$exception_sources',
                        label: 'Source',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.exception,
                    },
                    {
                        key: '$exception_functions',
                        label: 'Function',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.exception,
                    },
                    {
                        key: '$exception_releases',
                        label: 'Name',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.String,
                        section: SECTIONS.release,
                    },
                    {
                        key: '$app_version',
                        label: 'Version',
                        type: PropertyFilterType.Event,
                        propertyType: PropertyType.Semver,
                        section: SECTIONS.release,
                    },
                ],
            }),
        [filterValues, setGroupValues, valueLoader]
    )

    const pickerTokens = useMemo(() => {
        const cohortsById = Object.fromEntries(cohorts.results.map((cohort) => [cohort.id, cohort]))
        const filterTokens = filterValues.map((filter, index) =>
            createPropertyFilterToken(filter, {
                cohortsById,
                propertyLabelFormatter: (filter) =>
                    (filter.key ? PROPERTY_LABELS[filter.key] : undefined) ??
                    ('label' in filter ? filter.label : filter.key),
                editNodeIds: editPathForPropertyFilter(filter),
                idSuffix: index,
                onRemove: () => setGroupValues(filterValues.filter((_, i) => i !== index)),
            })
        )
        return [status.token, assignee.token, ...filterTokens].filter(Boolean) as FilterPickerToken[]
    }, [assignee.token, cohorts.results, filterValues, setGroupValues, status.token])

    return {
        pickerRootNodes: [status.node, assignee.node, ...propertyNodes],
        pickerTokens,
    }
}

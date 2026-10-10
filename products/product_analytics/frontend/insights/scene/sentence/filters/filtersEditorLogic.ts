import {
    MakeLogicType,
    actions,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import type { LogicWrapper } from 'kea'

import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    propertyFilterTypeToPropertyDefinitionType,
} from 'lib/components/PropertyFilters/utils'
import { objectsEqual } from 'lib/utils/objects'
import { isOperatorDate } from 'lib/utils/operators'
import { toParams } from 'lib/utils/url'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { insightLogicType } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import type { QuerySourceUpdate, insightVizDataLogicType } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { projectLogic } from 'scenes/projectLogic'
import type { projectLogicType } from 'scenes/projectLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import type { teamLogicType } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import type { cohortsModelType } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import type { propertyDefinitionsModelType } from '~/models/propertyDefinitionsModel'
import type { Node } from '~/queries/schema/schema-general'
import { isEventsNode, isInsightQueryWithSeries } from '~/queries/utils'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'
import type {
    AnyPropertyFilter,
    InsightLogicProps,
    PropertyDefinitionType,
    PropertyGroupFilter,
    PropertyOperator,
} from '~/types'

import type { PickedProperty } from '../PropertyPickerPopover'
import { buildTargetFilters } from './buildFilterProperties'
import { describeLockedFilter } from './describeLockedFilter'
import {
    defaultFilterOperator,
    filterOperatorOptions,
    filterValueKind,
    filterValueList,
    valueForOperator,
} from './filterOperatorOptions'
import type { FilterOperatorOption, FilterValueKind } from './filterOperatorOptions'
import { filtersTargetKey } from './filtersTarget'
import type { FiltersTarget } from './filtersTarget'
import { emptyFilterGroup, parseFilterRows } from './parseFilterRows'
import type { EditableFilter, EditableFilterRow, FilterEditorRow, FiltersDraft, SavedFilters } from './parseFilterRows'

export interface FiltersEditorLogicProps {
    insightProps: InsightLogicProps
    target: FiltersTarget
}

export type FiltersEditorStatus = 'loading' | 'unavailable' | 'ready'

/** `none` means the filter has no suggestions to load, such as a date. */
export type ValueSuggestionsStatus = 'none' | 'loading' | 'loaded' | 'error'

export interface EditableFilterRowView {
    id: string
    kind: 'filter'
    property: { key: string; type: string }
    label: string
    operator: PropertyOperator
    operatorOptions: FilterOperatorOption[]
    valueKind: FilterValueKind
    values: string[]
    valuePlaceholder: string
    search: string
    valueOptions: string[]
    suggestionsStatus: ValueSuggestionsStatus
}

export interface LockedFilterRowView {
    id: string
    kind: 'locked'
    description: string
}

export type FilterRowView = EditableFilterRowView | LockedFilterRowView

export interface FilterGroupView {
    id: string
    /** The name of the group when the editor shows more than one. */
    title: string
    matchMode: FilterLogicalOperator
    showMatchMode: boolean
    rows: FilterRowView[]
}

type QuerySource = insightVizDataLogicType['values']['querySource']
type FiltersToWrite = PropertyGroupFilter | AnyPropertyFilter[] | undefined

const TYPED_VALUE_WRITE_DELAY_MS = 400

function filterFromPick(property: PickedProperty): EditableFilter {
    const operator = defaultFilterOperator(property.propertyType)
    const base = { key: property.key, operator, value: valueForOperator(operator, operator, undefined) }
    switch (property.type) {
        case 'person':
            return { ...base, type: PropertyFilterType.Person }
        case 'session':
            return { ...base, type: PropertyFilterType.Session }
        case 'group':
            return { ...base, type: PropertyFilterType.Group, group_type_index: property.groupTypeIndex }
        default:
            return { ...base, type: PropertyFilterType.Event }
    }
}

function canSuggestValues(filter: EditableFilter, projectId: number | null): boolean {
    if (isOperatorDate(filter.operator)) {
        return false
    }
    return filter.type !== PropertyFilterType.Group || (projectId !== null && filter.group_type_index != null)
}

function rowFromPick(id: string, property: PickedProperty): EditableFilterRow {
    return {
        id,
        kind: 'filter',
        filter: filterFromPick(property),
        propertyType: property.propertyType,
        label: property.label,
    }
}

function unusedId(prefix: string, takenIds: string[]): string {
    let number = 0
    while (takenIds.includes(`${prefix}-${number}`)) {
        number++
    }
    return `${prefix}-${number}`
}

function findRow(draft: FiltersDraft, id: string): FilterEditorRow | undefined {
    return draft.groups.flatMap((group) => group.rows).find((row) => row.id === id)
}

function withAddedRow(draft: FiltersDraft, groupId: string, property: PickedProperty): FiltersDraft {
    const id = unusedId(
        'added',
        draft.groups.flatMap((group) => group.rows.map((row) => row.id))
    )
    return {
        ...draft,
        groups: draft.groups.map((group) =>
            group.id === groupId ? { ...group, rows: [...group.rows, rowFromPick(id, property)] } : group
        ),
    }
}

function withUpdatedRow(
    draft: FiltersDraft,
    id: string,
    update: (row: EditableFilterRow) => EditableFilterRow
): FiltersDraft {
    return {
        ...draft,
        groups: draft.groups.map((group) => ({
            ...group,
            rows: group.rows.map((row) => (row.id === id && row.kind === 'filter' ? update(row) : row)),
        })),
    }
}

function withoutRow(draft: FiltersDraft, id: string): FiltersDraft {
    return {
        ...draft,
        groups: draft.groups.map((group) => ({ ...group, rows: group.rows.filter((row) => row.id !== id) })),
    }
}

function withAddedGroup(draft: FiltersDraft): FiltersDraft {
    const id = unusedId(
        'added-group',
        draft.groups.map((group) => group.id)
    )
    return { ...draft, groups: [...draft.groups, emptyFilterGroup(id)] }
}

function withoutGroup(draft: FiltersDraft, groupId: string): FiltersDraft {
    const groups = draft.groups.filter((group) => group.id !== groupId)
    return { ...draft, groups: groups.length > 0 ? groups : [emptyFilterGroup(groupId)] }
}

function withoutKey(record: Record<string, string>, id: string): Record<string, string> {
    const { [id]: _removed, ...rest } = record
    return rest
}

function seriesNode(querySource: QuerySource, seriesIndex: number): { properties?: AnyPropertyFilter[] } | undefined {
    return querySource && isInsightQueryWithSeries(querySource) ? querySource.series[seriesIndex] : undefined
}

function savedTargetFilters(
    target: FiltersTarget,
    querySource: QuerySource,
    insightProperties: SavedFilters
): SavedFilters {
    return target.kind === 'series' ? seriesNode(querySource, target.seriesIndex)?.properties : insightProperties
}

// The saved filters in the shape the editor writes, so that the two compare equal when nothing differs.
function asWritten(target: FiltersTarget, savedProperties: SavedFilters): FiltersToWrite {
    return buildTargetFilters(target, parseFilterRows(savedProperties))
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface filtersEditorLogicValues {
    insightLoading: insightLogicType['values']['insightLoading'] // insightLogic
    querySource: QuerySource // insightVizDataLogic
    insightProperties: insightVizDataLogicType['values']['properties'] // insightVizDataLogic
    cohortsById: cohortsModelType['values']['cohortsById'] // cohortsModel
    describeProperty: propertyDefinitionsModelType['values']['describeProperty'] // propertyDefinitionsModel
    options: propertyDefinitionsModelType['values']['options'] // propertyDefinitionsModel
    currentProjectId: projectLogicType['values']['currentProjectId'] // projectLogic
    currentTeam: teamLogicType['values']['currentTeam'] // teamLogic
    canAddGroup: boolean
    draft: FiltersDraft
    eventNames: string[]
    filterGroups: FilterGroupView[]
    filterTestAccounts: boolean
    filtersToWrite: FiltersToWrite
    groupsMatchMode: FilterLogicalOperator
    hasTestAccountFilters: boolean
    savedProperties: SavedFilters
    showGroups: boolean
    status: FiltersEditorStatus
    valueSearch: Record<string, string>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface filtersEditorLogicActions {
    setQuery: (
        query: Node<Record<string, any>> | null,
        fromUrl?: boolean | undefined
    ) => {
        fromUrl: boolean
        query: Node<Record<string, any>> | null
    } // insightVizDataLogic
    updateQuerySource: (querySource: QuerySourceUpdate) => {
        querySource: QuerySourceUpdate
    } // insightVizDataLogic
    loadPropertyValues: (payload: {
        endpoint: string | undefined
        eventNames?: string[]
        newInput: string | undefined
        properties?: {
            key: string
            values: string | string[]
        }[]
        propertyKey: string
        refresh?: string
        type: PropertyDefinitionType
    }) => {
        endpoint: string | undefined
        eventNames?: string[] | undefined
        newInput: string | undefined
        properties?:
            | {
                  key: string
                  values: string | string[]
              }[]
            | undefined
        propertyKey: string
        refresh?: string | undefined
        type: PropertyDefinitionType
    } // propertyDefinitionsModel
    setLocalDefault: (value: boolean) => {
        value: boolean
    } // filterTestAccountsDefaultsLogic
    addFilter: (
        groupId: string,
        property: PickedProperty
    ) => {
        groupId: string
        property: PickedProperty
    }
    addGroup: () => {
        value: true
    }
    changeFilterOperator: (
        id: string,
        operator: PropertyOperator
    ) => {
        id: string
        operator: PropertyOperator
    }
    changeFilterProperty: (
        id: string,
        property: PickedProperty
    ) => {
        id: string
        property: PickedProperty
    }
    changeFilterValue: (
        id: string,
        value: string | string[]
    ) => {
        id: string
        value: string | string[]
    }
    removeGroup: (groupId: string) => {
        groupId: string
    }
    removeRow: (id: string) => {
        id: string
    }
    resetDraft: (draft: FiltersDraft) => {
        draft: FiltersDraft
    }
    searchFilterValues: (
        id: string,
        search: string
    ) => {
        id: string
        search: string
    }
    setFilterTestAccounts: (checked: boolean) => {
        checked: boolean
    }
    setGroupMatchMode: (
        groupId: string,
        matchMode: FilterLogicalOperator
    ) => {
        groupId: string
        matchMode: FilterLogicalOperator
    }
    setGroupsMatchMode: (matchMode: FilterLogicalOperator) => {
        matchMode: FilterLogicalOperator
    }
}

export type filtersEditorLogicType = MakeLogicType<
    filtersEditorLogicValues,
    filtersEditorLogicActions,
    FiltersEditorLogicProps
>

function writeFilters(logic: Pick<filtersEditorLogicType, 'actions' | 'values' | 'props'>): void {
    const { target } = logic.props
    const filters = logic.values.filtersToWrite
    if (objectsEqual(filters, asWritten(target, logic.values.savedProperties))) {
        return
    }
    if (target.kind === 'insight') {
        logic.actions.updateQuerySource({ properties: filters })
        return
    }
    const querySource = logic.values.querySource
    if (!querySource || !isInsightQueryWithSeries(querySource) || !querySource.series[target.seriesIndex]) {
        return
    }
    const series = querySource.series.map((node, index) => {
        if (index !== target.seriesIndex) {
            return node
        }
        const { properties: _replaced, ...rest } = node
        return filters ? { ...rest, properties: filters } : rest
    })
    logic.actions.updateQuerySource({ series } as QuerySourceUpdate)
}

export const filtersEditorLogic: LogicWrapper<filtersEditorLogicType> = kea<filtersEditorLogicType>([
    props({} as FiltersEditorLogicProps),
    key((props) => `${keyForInsightLogicProps('new')(props.insightProps)}/${filtersTargetKey(props.target)}`),
    path((key) => [
        'products',
        'product_analytics',
        'insights',
        'scene',
        'sentence',
        'filters',
        'filtersEditorLogic',
        key,
    ]),
    connect((props: FiltersEditorLogicProps) => ({
        values: [
            insightLogic(props.insightProps),
            ['insightLoading'],
            insightVizDataLogic(props.insightProps),
            ['querySource', 'properties as insightProperties'],
            cohortsModel,
            ['cohortsById'],
            propertyDefinitionsModel,
            ['describeProperty', 'options'],
            projectLogic,
            ['currentProjectId'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [
            insightVizDataLogic(props.insightProps),
            ['setQuery', 'updateQuerySource'],
            propertyDefinitionsModel,
            ['loadPropertyValues'],
            filterTestAccountsDefaultsLogic,
            ['setLocalDefault'],
        ],
    })),
    actions({
        addFilter: (groupId: string, property: PickedProperty) => ({ groupId, property }),
        addGroup: true,
        changeFilterOperator: (id: string, operator: PropertyOperator) => ({ id, operator }),
        changeFilterProperty: (id: string, property: PickedProperty) => ({ id, property }),
        changeFilterValue: (id: string, value: string | string[]) => ({ id, value }),
        removeGroup: (groupId: string) => ({ groupId }),
        removeRow: (id: string) => ({ id }),
        resetDraft: (draft: FiltersDraft) => ({ draft }),
        searchFilterValues: (id: string, search: string) => ({ id, search }),
        setFilterTestAccounts: (checked: boolean) => ({ checked }),
        setGroupMatchMode: (groupId: string, matchMode: FilterLogicalOperator) => ({ groupId, matchMode }),
        setGroupsMatchMode: (matchMode: FilterLogicalOperator) => ({ matchMode }),
    }),
    reducers({
        draft: [
            (state: any, props: FiltersEditorLogicProps): FiltersDraft => {
                const vizSelectors = insightVizDataLogic(props.insightProps).selectors
                return parseFilterRows(
                    savedTargetFilters(props.target, vizSelectors.querySource(state), vizSelectors.properties(state))
                )
            },
            {
                resetDraft: (_, { draft }) => draft,
                addFilter: (state, { groupId, property }) => withAddedRow(state, groupId, property),
                addGroup: (state) => withAddedGroup(state),
                changeFilterProperty: (state, { id, property }) =>
                    withUpdatedRow(state, id, (row) => rowFromPick(row.id, property)),
                changeFilterOperator: (state, { id, operator }) =>
                    withUpdatedRow(state, id, (row) => ({
                        ...row,
                        filter: {
                            ...row.filter,
                            operator,
                            value: valueForOperator(operator, row.filter.operator, row.filter.value),
                        },
                    })),
                changeFilterValue: (state, { id, value }) =>
                    withUpdatedRow(state, id, (row) => ({ ...row, filter: { ...row.filter, value } })),
                removeGroup: (state, { groupId }) => withoutGroup(state, groupId),
                removeRow: (state, { id }) => withoutRow(state, id),
                setGroupMatchMode: (state, { groupId, matchMode }) => ({
                    ...state,
                    groups: state.groups.map((group) => (group.id === groupId ? { ...group, matchMode } : group)),
                }),
                setGroupsMatchMode: (state, { matchMode }) => ({ ...state, groupsMatchMode: matchMode }),
            },
        ],
        valueSearch: [
            {} as Record<string, string>,
            {
                searchFilterValues: (state, { id, search }) => ({ ...state, [id]: search }),
                changeFilterProperty: (state, { id }) => withoutKey(state, id),
                removeRow: (state, { id }) => withoutKey(state, id),
                // A row added later can reuse the id of a row in the removed group.
                removeGroup: () => ({}),
                resetDraft: () => ({}),
            },
        ],
    }),
    selectors(({ props }) => ({
        savedProperties: [
            (s) => [s.querySource, s.insightProperties],
            (
                querySource: QuerySource,
                insightProperties: filtersEditorLogicValues['insightProperties']
            ): SavedFilters => savedTargetFilters(props.target, querySource, insightProperties),
        ],
        status: [
            (s) => [s.querySource, s.insightLoading],
            (querySource: QuerySource, insightLoading: boolean): FiltersEditorStatus => {
                if (!querySource) {
                    return insightLoading ? 'loading' : 'unavailable'
                }
                return props.target.kind === 'series' && !seriesNode(querySource, props.target.seriesIndex)
                    ? 'unavailable'
                    : 'ready'
            },
        ],
        groupsMatchMode: [(s) => [s.draft], (draft: FiltersDraft): FilterLogicalOperator => draft.groupsMatchMode],
        showGroups: [(s) => [s.draft], (draft: FiltersDraft): boolean => draft.groups.length > 1],
        // A second group next to an empty one would leave two blank groups to choose between.
        canAddGroup: [
            (s) => [s.draft],
            (draft: FiltersDraft): boolean =>
                props.target.kind === 'insight' && draft.groups.every((group) => group.rows.length > 0),
        ],
        filtersToWrite: [
            (s) => [s.draft],
            (draft: FiltersDraft): FiltersToWrite => buildTargetFilters(props.target, draft),
        ],
        eventNames: [
            (s) => [s.querySource],
            (querySource: QuerySource): string[] => {
                if (!querySource || !isInsightQueryWithSeries(querySource)) {
                    return []
                }
                const { target } = props
                const nodes = target.kind === 'series' ? [querySource.series[target.seriesIndex]] : querySource.series
                const names = new Set<string>()
                for (const node of nodes) {
                    // An action or an "all events" series can match any event, so its values cannot be narrowed.
                    if (!node || !isEventsNode(node) || !node.event) {
                        return []
                    }
                    names.add(node.event)
                }
                return Array.from(names)
            },
        ],
        hasTestAccountFilters: [
            (s) => [s.currentTeam],
            (currentTeam: filtersEditorLogicValues['currentTeam']): boolean =>
                (currentTeam?.test_account_filters ?? []).length > 0,
        ],
        filterTestAccounts: [
            (s) => [s.querySource, s.hasTestAccountFilters],
            (querySource: QuerySource, hasTestAccountFilters: boolean): boolean =>
                hasTestAccountFilters && !!querySource?.filterTestAccounts,
        ],
        filterGroups: [
            (s) => [s.draft, s.valueSearch, s.describeProperty, s.options, s.cohortsById, s.currentProjectId],
            (
                draft: FiltersDraft,
                valueSearch: Record<string, string>,
                describeProperty: filtersEditorLogicValues['describeProperty'],
                options: filtersEditorLogicValues['options'],
                cohortsById: filtersEditorLogicValues['cohortsById'],
                currentProjectId: number | null
            ): FilterGroupView[] => {
                const rowView = (row: FilterEditorRow): FilterRowView => {
                    if (row.kind !== 'filter') {
                        return { id: row.id, kind: 'locked', description: describeLockedFilter(row.value, cohortsById) }
                    }
                    const { filter } = row
                    const propertyType =
                        describeProperty(
                            filter.key,
                            propertyFilterTypeToPropertyDefinitionType(filter.type),
                            filter.type === PropertyFilterType.Group
                                ? (filter.group_type_index ?? undefined)
                                : undefined
                        ) ?? row.propertyType
                    const suggestsValues = canSuggestValues(filter, currentProjectId)
                    const loaded = suggestsValues ? options[filter.key] : undefined
                    const valueKind = filterValueKind(filter.operator, filter.value)
                    const values = valueKind === 'none' ? [] : filterValueList(filter.value)
                    const search = valueSearch[row.id] ?? ''
                    const suggestions = (loaded?.values ?? [])
                        .map((value) => value.name)
                        .filter((name) => name !== undefined && name !== null && name !== '')
                        .map(String)
                    return {
                        id: row.id,
                        kind: 'filter',
                        property: { key: filter.key, type: filter.type },
                        label:
                            row.label ??
                            getCoreFilterDefinition(
                                filter.key,
                                PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]
                            )?.label ??
                            filter.label ??
                            filter.key,
                        operator: filter.operator,
                        operatorOptions: filterOperatorOptions(propertyType, filter.operator),
                        valueKind,
                        values,
                        valuePlaceholder: isOperatorDate(filter.operator)
                            ? '2026-01-31 or -7d'
                            : valueKind === 'many'
                              ? 'Add a value'
                              : 'Value',
                        search,
                        // A chips input only offers list items, so the typed text joins the list to allow any value.
                        valueOptions: Array.from(
                            new Set(
                                valueKind === 'many'
                                    ? [...suggestions, ...values, ...(search.trim() ? [search.trim()] : [])]
                                    : suggestions
                            )
                        ),
                        // Suggestions that were never requested are not known to be empty, so they count as loading.
                        suggestionsStatus: suggestsValues ? (loaded?.status ?? 'loading') : 'none',
                    }
                }
                return draft.groups.map((group, index) => ({
                    id: group.id,
                    title: `Group ${index + 1}`,
                    matchMode: group.matchMode,
                    // The filters of one event always all apply, so there is nothing to choose.
                    showMatchMode: props.target.kind === 'insight' && group.rows.length > 1,
                    rows: group.rows.map(rowView),
                }))
            },
        ],
    })),
    listeners((logic) => {
        const { actions, values, selectors, props } = logic
        return {
            changeFilterOperator: () => writeFilters(logic),
            changeFilterProperty: () => writeFilters(logic),
            removeGroup: () => writeFilters(logic),
            removeRow: () => writeFilters(logic),
            setGroupMatchMode: () => writeFilters(logic),
            setGroupsMatchMode: () => writeFilters(logic),
            changeFilterValue: async ({ id, value }, breakpoint) => {
                if (typeof value === 'string') {
                    actions.searchFilterValues(id, value)
                    await breakpoint(TYPED_VALUE_WRITE_DELAY_MS)
                }
                writeFilters(logic)
            },
            setFilterTestAccounts: ({ checked }) => {
                actions.updateQuerySource({ filterTestAccounts: checked })
                actions.setLocalDefault(checked)
            },
            searchFilterValues: ({ id, search }) => {
                const row = findRow(values.draft, id)
                if (!row || row.kind !== 'filter' || !canSuggestValues(row.filter, values.currentProjectId)) {
                    return
                }
                const { filter } = row
                const loaded = values.options[filter.key]
                if (loaded?.status === 'loaded' && (loaded.searchInput ?? '') === search) {
                    return
                }
                actions.loadPropertyValues({
                    endpoint:
                        filter.type === PropertyFilterType.Group
                            ? `api/projects/${values.currentProjectId}/groups/property_values?${toParams({
                                  key: filter.key,
                                  group_type_index: filter.group_type_index,
                              })}`
                            : undefined,
                    type: propertyFilterTypeToPropertyDefinitionType(filter.type),
                    newInput: search,
                    propertyKey: filter.key,
                    eventNames: filter.type === PropertyFilterType.Event ? values.eventNames : [],
                    properties: [],
                })
            },
            setQuery: (_, __, ___, previousState) => {
                const saved = asWritten(props.target, values.savedProperties)
                // A query change that leaves the filters alone must not discard a value the user is still typing.
                if (objectsEqual(saved, asWritten(props.target, selectors.savedProperties(previousState)))) {
                    return
                }
                if (!objectsEqual(saved, values.filtersToWrite)) {
                    actions.resetDraft(parseFilterRows(values.savedProperties))
                }
            },
        }
    }),
    beforeUnmount((logic) => {
        writeFilters(logic)
    }),
])

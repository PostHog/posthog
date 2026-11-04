import { ApiError } from 'lib/api-error'

import type { WorkflowViewApi, WorkflowViewFilterApi, WorkflowViewStateApi } from '../../generated/api.schemas'
import { WorkflowViewFacetEnumApi } from '../../generated/api.schemas'
import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
    facetFilterKey,
    findFacet,
    serializeFacetQuery,
} from './FacetSearchBar/facetQuery'
import { DEFAULT_COLUMNS, OPTIONAL_COLUMNS, OptionalColumn } from './workflowListLabels'

export type WorkflowSavedView = Pick<WorkflowViewApi, 'id' | 'name' | 'state' | 'version' | 'default_key'> & {
    builtIn?: boolean
}

export const BUILT_IN_WORKFLOW_VIEWS: WorkflowSavedView[] = [
    {
        id: 'all',
        name: 'All',
        state: { filters: [], text: '', columns: DEFAULT_COLUMNS },
        version: 0,
        default_key: null,
        builtIn: true,
    },
    {
        id: 'needs-attention',
        name: 'Needs attention',
        state: {
            filters: [
                { facet: 'health', value: 'failing', negated: false },
                { facet: 'status', value: 'active', negated: false },
            ],
            text: '',
            columns: ['last_7_days', 'health'],
        },
        version: 0,
        default_key: null,
        builtIn: true,
    },
    {
        id: 'drafts',
        name: 'Drafts',
        state: { filters: [{ facet: 'status', value: 'draft', negated: false }], text: '', columns: DEFAULT_COLUMNS },
        version: 0,
        default_key: null,
        builtIn: true,
    },
]

export function normalizeViewColumns(columns: readonly string[]): OptionalColumn[] {
    return OPTIONAL_COLUMNS.filter((column) => columns.includes(column))
}

export function workflowViewValue(state: WorkflowViewStateApi): FacetSearchValue {
    return {
        filters: state.filters.map((filter) => ({ ...filter, negated: filter.negated ?? false })),
        text: state.text,
    }
}

export function savedViewChanges(
    view: WorkflowSavedView,
    value: FacetSearchValue,
    columns: OptionalColumn[]
): string[] {
    const signature = (filters: FacetSearchValue['filters']): string =>
        filters
            .map((filter) => serializeFacetQuery([filter]))
            .sort()
            .join(' ')
    const changes: string[] = []
    if (signature(workflowViewValue(view.state).filters) !== signature(value.filters)) {
        changes.push('filters')
    }
    if (view.state.text !== value.text.trim()) {
        changes.push('search')
    }
    if (normalizeViewColumns(view.state.columns).join(',') !== columns.join(',')) {
        changes.push('columns')
    }
    return changes
}

export function workflowViewState(value: FacetSearchValue, columns: OptionalColumn[]): WorkflowViewStateApi {
    const allowed = Object.values(WorkflowViewFacetEnumApi)
    const filters = value.filters.filter((filter): filter is FacetFilter & { facet: WorkflowViewFilterApi['facet'] } =>
        allowed.some((facet) => facet === filter.facet)
    )
    return { filters, text: value.text.trim(), columns }
}

function resolvedValue<TItem>(facets: FacetDefinition<TItem>[], filter: FacetFilter): string {
    const facet = findFacet(facets, filter.facet)
    return (facet?.resolveValue?.(filter.value) ?? filter.value).toLowerCase()
}

export function mergeAddedFilters<TItem>(
    viewFilters: FacetFilter[],
    added: FacetFilter[],
    facets: FacetDefinition<TItem>[]
): FacetFilter[] {
    const overrides = (addedFilter: FacetFilter, viewFilter: FacetFilter): boolean =>
        addedFilter.facet === viewFilter.facet &&
        ((!addedFilter.negated && !viewFilter.negated) ||
            resolvedValue(facets, addedFilter) === resolvedValue(facets, viewFilter))
    const kept = viewFilters.filter((viewFilter) => !added.some((filter) => overrides(filter, viewFilter)))
    return [...kept, ...added]
}

export function addedFiltersAfterEdit(
    previousFilters: FacetFilter[],
    previouslyAdded: FacetFilter[],
    filters: FacetFilter[]
): FacetFilter[] {
    const previousKeys = new Set(previousFilters.map(facetFilterKey))
    const addedKeys = new Set(previouslyAdded.map(facetFilterKey))
    return filters.filter(
        (filter) => addedKeys.has(facetFilterKey(filter)) || !previousKeys.has(facetFilterKey(filter))
    )
}

export function filtersFromView(
    viewFilters: FacetFilter[],
    added: FacetFilter[],
    filters: FacetFilter[]
): FacetFilter[] {
    const viewKeys = new Set(viewFilters.map(facetFilterKey))
    const addedKeys = new Set(added.map(facetFilterKey))
    return filters.filter((filter) => viewKeys.has(facetFilterKey(filter)) && !addedKeys.has(facetFilterKey(filter)))
}

export type SavedViewAction = 'save-as' | 'update' | 'rename' | 'delete' | 'restore' | 'reset'

export function isMissingViewError(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404
}

export function savedViewFailureMessage(action: SavedViewAction, viewName: string, error: unknown): string {
    return `${failedActionMessage(action, viewName)} ${failureReason(action, error)}`
}

function failedActionMessage(action: SavedViewAction, viewName: string): string {
    const messages: Record<SavedViewAction, string> = {
        'save-as': "Couldn't save the new view.",
        update: `Couldn't update ${viewName}.`,
        rename: `Couldn't rename ${viewName}.`,
        delete: `Couldn't delete ${viewName}.`,
        restore: "Couldn't restore My workflows.",
        reset: `Couldn't load the latest version of ${viewName}.`,
    }
    return messages[action]
}

function failureReason(action: SavedViewAction, error: unknown): string {
    const status = error instanceof ApiError ? error.status : undefined
    if (status === 403) {
        return action === 'reset'
            ? 'You need viewer access to workflows to see shared views.'
            : 'You need editor access to workflows to change shared views.'
    }
    if (status === 404) {
        return action === 'update'
            ? 'It was deleted by someone else. Your changes are still here. Save them as a new view to keep them.'
            : 'It was deleted by someone else.'
    }
    if (status === 409) {
        return action === 'update'
            ? 'This view changed since you opened it. Your changes are still here. Save them as a new view or reset to the latest version.'
            : 'This view changed since you opened it. Reset to the latest version and try again.'
    }
    if (error instanceof ApiError && status === 400 && error.detail) {
        return error.detail
    }
    return 'Check your connection and try again.'
}

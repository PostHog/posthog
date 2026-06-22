import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsAttributesRetrieve, logsFieldValuesCreate } from '../../../generated/api'
import { _LogFieldValueApi, _LogPropertyFilterApi, _LogsFieldValuesBodyApi } from '../../../generated/api.schemas'
import type { fieldCountsLogicType } from './fieldCountsLogicType'
import { FIELDS, FieldConfig } from './fields'

// Broad, filter-independent window for the "which resource attributes does this tenant emit" probe.
// Cheap: keys-only group-by on the log_attributes aggregation table (no value scan).
const PRESENCE_LOOKBACK = { date_from: '-90d' }

export interface FieldCountsLogicProps {
    id: string
}

/**
 * Per-field values + counts, cross-filtered server-side: each field's results reflect every active
 * filter except its own selection (the backend excludes the field's own column or resource-attribute
 * filter). Values come back ordered by count descending. The rail is config-driven, so this fetches
 * one request per field in FIELDS, keyed by field.key. A per-field type-ahead search re-fetches only
 * that field (its CH group-by is a full scan, so we don't refetch the others on every keystroke).
 */
export const fieldCountsLogic = kea<fieldCountsLogicType>([
    props({ id: 'default' } as FieldCountsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FieldRail', 'fieldCountsLogic', key]),

    connect((props: FieldCountsLogicProps) => ({
        values: [
            logsViewerFiltersLogic({ id: props.id }),
            ['filters', 'utcDateRange', 'queryFilterGroup'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    actions({
        setFieldSearch: (fieldKey: string, search: string) => ({ fieldKey, search }),
    }),

    reducers({
        fieldSearch: [
            {} as Record<string, string>,
            {
                setFieldSearch: (state, { fieldKey, search }) => ({ ...state, [fieldKey]: search }),
            },
        ],
        // Keys currently being fetched, so each field can show its own loading state. Set from the
        // load action's argument (null = all fields); cleared when the fetch settles.
        loadingFieldKeys: [
            [] as string[],
            {
                loadFieldValues: (_, fieldKeys: string[] | null) => fieldKeys ?? FIELDS.map((f) => f.key),
                loadFieldValuesSuccess: () => [],
                loadFieldValuesFailure: () => [],
                loadFieldValuesForKey: (_, fieldKey: string) => [fieldKey],
                loadFieldValuesForKeySuccess: () => [],
                loadFieldValuesForKeyFailure: () => [],
            },
        ],
        // Latches true once the presence probe settles (success or failure). Until then the value
        // fetch is deferred, so column fields aren't fetched on mount and then re-fetched once
        // presence resolves and the resource-attribute fields become visible.
        presenceLoaded: [
            false,
            {
                loadPresentResourceKeysSuccess: () => true,
                loadPresentResourceKeysFailure: () => true,
            },
        ],
    }),

    loaders(({ values }) => {
        const fetchField = async (field: FieldConfig): Promise<_LogFieldValueApi[]> => {
            if (!values.currentTeamId) {
                return []
            }
            const group = values.queryFilterGroup as UniversalFiltersGroup
            const filterGroup = ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ??
                []) as unknown as _LogPropertyFilterApi[]
            const target: Partial<_LogsFieldValuesBodyApi> =
                field.source.type === 'column'
                    ? { column: field.source.column }
                    : { resourceAttribute: field.source.key }
            const response = await logsFieldValuesCreate(String(values.currentTeamId), {
                query: {
                    ...target,
                    dateRange: values.utcDateRange,
                    severityLevels: values.filters.severityLevels ?? [],
                    serviceNames: values.filters.serviceNames ?? [],
                    searchTerm: values.filters.searchTerm || undefined,
                    fieldSearch: values.fieldSearch[field.key] || undefined,
                    filterGroup,
                },
            })
            return response.results
        }

        // Fetch each field independently and merge into the existing record. allSettled (not all) so
        // one field's failed request leaves the others' counts intact instead of wiping the batch.
        const mergeFetched = async (fields: FieldConfig[]): Promise<Record<string, _LogFieldValueApi[]>> => {
            const settled = await Promise.allSettled(
                fields.map(async (field) => [field.key, await fetchField(field)] as const)
            )
            const fetched = settled
                .filter(
                    (s): s is PromiseFulfilledResult<readonly [string, _LogFieldValueApi[]]> => s.status === 'fulfilled'
                )
                .map((s) => s.value)
            return { ...values.fieldValues, ...Object.fromEntries(fetched) }
        }

        return {
            fieldValues: [
                {} as Record<string, _LogFieldValueApi[]>,
                {
                    // Refetch all fields (null) or a subset — used when filters change.
                    loadFieldValues: async (fieldKeys: string[] | null, breakpoint) => {
                        await breakpoint(300)
                        const fields = fieldKeys
                            ? values.visibleFields.filter((f) => fieldKeys.includes(f.key))
                            : values.visibleFields
                        const result = await mergeFetched(fields)
                        breakpoint()
                        return result
                    },
                    // A single field's type-ahead search. Separate action so its breakpoint is independent:
                    // typing in one field's search must not cancel a still-debouncing full reload.
                    loadFieldValuesForKey: async (fieldKey: string, breakpoint) => {
                        await breakpoint(300)
                        const field = FIELDS.find((f) => f.key === fieldKey)
                        const result = field ? await mergeFetched([field]) : values.fieldValues
                        breakpoint()
                        return result
                    },
                },
            ],
            presentResourceKeys: [
                [] as string[],
                {
                    // Which resource attribute keys the tenant emits — gates which curated fields render.
                    loadPresentResourceKeys: async () => {
                        if (!values.currentTeamId) {
                            return []
                        }
                        const response = await logsAttributesRetrieve(String(values.currentTeamId), {
                            attribute_type: 'resource',
                            dateRange: PRESENCE_LOOKBACK,
                            limit: 100,
                        })
                        return response.results.map((r) => r.name)
                    },
                },
            ],
        }
    }),

    selectors({
        // Column fields always render; resource-attribute fields only when the tenant emits the key.
        visibleFields: [
            (s) => [s.presentResourceKeys],
            (presentResourceKeys): FieldConfig[] =>
                FIELDS.filter((f) => f.source.type === 'column' || presentResourceKeys.includes(f.source.key)),
        ],
    }),

    listeners(({ actions }) => ({
        // A field's search changed — refetch only that field, via its own action so it doesn't
        // cancel a still-debouncing full reload (independent breakpoint).
        setFieldSearch: ({ fieldKey }) => actions.loadFieldValuesForKey(fieldKey),
        // Presence settled — drive the first full fetch now that visibleFields is known. On failure
        // we still fetch so the column fields (Level/Service) load even if the probe errored.
        loadPresentResourceKeysSuccess: () => actions.loadFieldValues(null),
        loadPresentResourceKeysFailure: () => actions.loadFieldValues(null),
    })),

    events(({ actions }) => ({
        afterMount: () => actions.loadPresentResourceKeys(),
    })),

    subscriptions(({ actions, values }) => {
        // Fires on mount (initial load) and on any change. We watch both `filters` (severity, service,
        // search, date, user filterGroup) and `queryFilterGroup` (which folds in pinnedFilters, e.g. the
        // person-tab distinct_id pin) so values re-fetch when the pinned scope changes too. `filterGroup`
        // feeds both, so a normal edit fires both — the 300ms debounce in the loader collapses that.
        const reloadAll = (): void => {
            // Before the presence probe settles, defer to loadPresentResourceKeys{Success,Failure}
            // so we issue one full fetch over the final visible set instead of two.
            if (values.presenceLoaded) {
                actions.loadFieldValues(null)
            }
        }
        return {
            filters: reloadAll,
            queryFilterGroup: reloadAll,
        }
    }),
])

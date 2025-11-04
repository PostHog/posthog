import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'

const mapPerson = (person: any): { distinct_id: string; created_at: string; properties: Record<string, any> } => {
    // The person data comes as a tuple [distinct_id, created_at, properties_json]
    // We need to parse the properties_json string if it exists
    if (!Array.isArray(person) || person.length === 0) {
        return { distinct_id: '', created_at: '', properties: {} }
    }
    const [distinctId, createdAt, propertiesJson] = person
    let properties: Record<string, any> = {}
    try {
        properties = JSON.parse(propertiesJson)
    } catch (e) {
        console.error('Error parsing person properties_json:', e)
    }
    return { distinct_id: distinctId, created_at: createdAt, properties }
}

export function LLMAnalyticsUsers(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setUsersSort } = useActions(llmAnalyticsLogic)
    const { usersQuery, usersSort } = useValues(llmAnalyticsLogic)

    const { renderSortableColumnTitle } = useSortableColumns(usersSort, setUsersSort)

    return (
        <DataTable
            query={{
                ...usersQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMAnalyticsUsers received a non-events query:', query.source)
                    return
                }
                const { filters = {} } = query.source
                const { dateRange = {} } = filters
                setDates(dateRange.date_from || null, dateRange.date_to || null)
                setShouldFilterTestAccounts(filters.filterTestAccounts || false)
                setPropertyFilters(filters.properties || [])
            }}
            context={{
                columns: {
                    user: {
                        title: 'Person',
                        render: function RenderPerson(x) {
                            const person = mapPerson(x.value)
                            return (
                                <PersonDisplay
                                    person={person}
                                    withIcon
                                    noPopover
                                    href={
                                        combineUrl(urls.llmAnalyticsTraces(), {
                                            filters: [
                                                {
                                                    type: PropertyFilterType.HogQL,
                                                    key: `distinct_id == '${person.distinct_id}'`,
                                                    value: null,
                                                },
                                            ],
                                        }).url
                                    }
                                />
                            )
                        },
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First Seen'),
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last Seen'),
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of traces created by this user">
                                {renderSortableColumnTitle('traces', 'Traces')}
                            </Tooltip>
                        ),
                    },
                    generations: {
                        renderTitle: () => (
                            <Tooltip title="Number of generations created by this user">
                                {renderSortableColumnTitle('generations', 'Generations')}
                            </Tooltip>
                        ),
                    },
                    errors: {
                        renderTitle: () => (
                            <Tooltip title="Number of errors encountered by this user">
                                {renderSortableColumnTitle('errors', 'Errors')}
                            </Tooltip>
                        ),
                    },
                    total_cost: {
                        renderTitle: () => (
                            <Tooltip title="Total cost of all generations for this user">
                                {renderSortableColumnTitle('total_cost', 'Cost')}
                            </Tooltip>
                        ),
                        render: function RenderCost({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>${Number(value).toFixed(4)}</span>
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-users"
        />
    )
}

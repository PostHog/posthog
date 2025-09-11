import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

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
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsLogic)
    const { usersQuery } = useValues(llmAnalyticsLogic)

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
                        title: 'First Seen',
                    },
                    last_seen: {
                        title: 'Last Seen',
                    },
                    traces: {
                        title: 'Traces (count)',
                    },
                    generations: {
                        title: 'Generations (count)',
                    },
                    total_cost: {
                        title: 'Total Cost (USD)',
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

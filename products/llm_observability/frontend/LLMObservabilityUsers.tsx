import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

import { llmObservabilityLogic } from './llmObservabilityLogic'

const mapPerson = (person: any): { distinct_id: string; created_at: string; properties: Record<string, any> } => {
    return {
        distinct_id: Array.isArray(person) && person.length > 0 ? person[0] : '',
        created_at: Array.isArray(person) && person.length > 1 ? person[1] : '',
        properties: Array.isArray(person) && person.length > 2 ? person[2] : {},
    }
}

export function LLMObservabilityUsers(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmObservabilityLogic)
    const { usersQuery } = useValues(llmObservabilityLogic)

    return (
        <DataTable
            query={usersQuery}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMObservabilityUsers received a non-events query:', query.source)
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
                                        combineUrl(urls.llmObservabilityTraces(), {
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
            uniqueKey="llm-observability-users"
        />
    )
}

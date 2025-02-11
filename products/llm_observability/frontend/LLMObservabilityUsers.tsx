import { useActions, useValues } from 'kea'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isEventsQuery } from '~/queries/utils'

import { llmObservabilityLogic } from './llmObservabilityLogic'

const mapPerson = (person: any): { distinct_id: string; created_at: string; properties: Record<string, any> } => {
    return {
        distinct_id: person[0],
        created_at: person[1],
        properties: person[2],
    }
}

export function LLMObservabilityUsers(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmObservabilityLogic)
    const { usersQuery } = useValues(llmObservabilityLogic)

    return (
        <DataTable
            query={usersQuery}
            setQuery={(query) => {
                if (!isEventsQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.after || null, query.source.before || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                setPropertyFilters(query.source.properties || [])
            }}
            context={{
                columns: {
                    user: {
                        title: 'Person',
                        render: function RenderPerson(x) {
                            const person = mapPerson(x.value)
                            return <PersonDisplay person={person} withIcon />
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
                        render: function RenderCost({ record, value }) {
                            if (record === null) {
                                return <span>N/A</span>
                            }
                            return <span>${value}</span>
                        },
                    },
                },
            }}
            uniqueKey="llm-observability-users"
        />
    )
}

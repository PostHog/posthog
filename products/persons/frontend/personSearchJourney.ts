import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'

import { QueryJourneyDescriptor } from '~/queries/nodes/DataNode/queryJourney'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

const personSearchJourney: QueryJourneyDescriptor = {
    startRequest: (queryId) =>
        startCustomerJourney({
            journey_name: 'person_search',
            resource_type: 'persons',
            resource_id: 'list',
            trigger: 'query_execution',
            readiness_scope: 'persons_list_query_to_table_commit',
            readiness_contract_version: 1,
            attempt_id: queryId,
        }),
}

export function getPersonSearchJourney(query: DataTableNode): QueryJourneyDescriptor | undefined {
    const source = query.source
    return query.showResultsTable !== false &&
        source.kind === NodeKind.ActorsQuery &&
        (!('source' in source) || source.source === undefined)
        ? personSearchJourney
        : undefined
}

import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

// The coverage count trims these characters before it treats an email as blank, so the list must match them too.
const MISSING_OR_BLANK_EMAIL: PersonPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.NotRegex,
    value: '[^ \\t\\n\\r]',
}

/** `personsSceneLogic` reads the query from the `q` hash param; renaming it there leaves this link unfiltered. */
export function unreachablePersonsUrl(): string {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            select: defaultDataTableColumns(NodeKind.ActorsQuery),
            properties: [MISSING_OR_BLANK_EMAIL],
        },
        full: true,
    }
    return combineUrl(urls.persons(), {}, { q: query }).url
}

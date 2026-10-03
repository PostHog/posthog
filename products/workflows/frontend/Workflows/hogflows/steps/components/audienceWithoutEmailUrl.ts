import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import {
    AnyPersonScopeFilter,
    AnyPropertyFilter,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

const HAS_NO_EMAIL: PersonPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.IsNotSet,
}

/** `personsSceneLogic` reads the query from the `q` hash param; renaming it there leaves this link unfiltered. */
export function audienceWithoutEmailUrl(audienceProperties: AnyPropertyFilter[]): string {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            select: defaultDataTableColumns(NodeKind.ActorsQuery),
            properties: [...audienceProperties, HAS_NO_EMAIL] as AnyPersonScopeFilter[],
        },
        full: true,
    }
    return combineUrl(urls.persons(), {}, { q: query }).url
}

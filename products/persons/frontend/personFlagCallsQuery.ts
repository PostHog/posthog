import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'
import { FLAG_CALLS_COLUMNS, flagCallsListQuery } from 'scenes/feature-flags/flagCallsListQuery'

import { DataTableNode } from '~/queries/schema/schema-general'

export function createInitialFlagCallsPayload(personId: string): DataTableNode {
    return flagCallsListQuery({
        select: FLAG_CALLS_COLUMNS.filter((column) => column !== PERSON_DISPLAY_NAME_COLUMN_NAME),
        personId,
    })
}

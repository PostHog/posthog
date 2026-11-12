import type { CompareFilter, Node } from '~/queries/schema/schema-general'

import { readsOnlyWarehouseTables } from './exceedsRetention'

export interface RetentionDeletionChart {
    isStickiness: boolean
    querySource: Node | null | undefined
    compareFilter: CompareFilter | null | undefined
}

export function showsRetentionDeletion({ isStickiness, querySource, compareFilter }: RetentionDeletionChart): boolean {
    return !isStickiness && !readsOnlyWarehouseTables(querySource) && !compareFilter?.compare
}

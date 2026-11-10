import type { CompareFilter, Node } from '~/queries/schema/schema-general'

import { readsOnlyWarehouseTables } from './exceedsRetention'

export function showsRetentionDeletion({
    isStickiness,
    days,
    querySource,
    compareFilter,
}: {
    isStickiness: boolean
    days: string[] | undefined
    querySource: Node | null | undefined
    compareFilter: CompareFilter | null | undefined
}): boolean {
    return !isStickiness && !!days?.length && !readsOnlyWarehouseTables(querySource) && !compareFilter?.compare
}

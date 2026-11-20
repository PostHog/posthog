import { DataWarehouseViewLink, ExternalDataSource } from '~/types'

export function customerRevenueViewName(source: ExternalDataSource): string {
    const sourcePrefix = source.prefix
        ? `${source.source_type.toLowerCase()}.${source.prefix.replace(/_+$/, '')}`
        : source.source_type.toLowerCase()
    return `${sourcePrefix}.customer_revenue_view`
}

export function findRevenueJoin(
    joins: DataWarehouseViewLink[],
    source: ExternalDataSource,
    joiningTableName: 'persons' | 'groups'
): DataWarehouseViewLink | undefined {
    const joinName = customerRevenueViewName(source)
    return joins.find((join) => join.source_table_name === joinName && join.joining_table_name === joiningTableName)
}

// Hardcoded on purpose: this is the exact join the backend expects for revenue analytics.
export function newRevenueJoin(
    source: ExternalDataSource,
    joiningTableName: 'persons' | 'groups',
    joiningTableKey: string
): Partial<DataWarehouseViewLink> {
    return {
        source_table_name: customerRevenueViewName(source),
        source_table_key: 'id',
        joining_table_name: joiningTableName,
        joining_table_key: joiningTableKey,
        field_name: joiningTableName,
    }
}

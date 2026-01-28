// Fixed UI columns - always present, not user-configurable
export const FIXED_COLUMN_TYPES = ['severityColor', 'selectCheckbox', 'expandRowButton'] as const
export type FixedColumnType = (typeof FIXED_COLUMN_TYPES)[number]

// User-configurable column types
export const CONFIGURABLE_COLUMN_TYPES = [
    'timestamp',
    'date',
    'time',
    'body',
    'distinctId',
    'sessionId',
    'attribute',
    'expression',
] as const
export type ConfigurableColumnType = (typeof CONFIGURABLE_COLUMN_TYPES)[number]

export const COLUMN_TYPES = [...FIXED_COLUMN_TYPES, ...CONFIGURABLE_COLUMN_TYPES] as const
export type ColumnType = (typeof COLUMN_TYPES)[number]

interface BaseColumn {
    id: string
    label?: string
    order?: number
    width: number
}

export interface FixedColumn extends BaseColumn {
    type: FixedColumnType
}

export interface BuiltInConfigurableColumn extends BaseColumn {
    type: 'timestamp' | 'date' | 'time' | 'body' | 'distinctId' | 'sessionId'
}

export interface AttributeColumn extends BaseColumn {
    id: `attribute-${string}`
    type: 'attribute'
    attributeKey: string
}

export interface ExpressionColumn extends BaseColumn {
    type: 'expression'
    expression: string
}

export type ConfigurableColumn = BuiltInConfigurableColumn | AttributeColumn | ExpressionColumn

export type Column = FixedColumn | ConfigurableColumn

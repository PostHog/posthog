import {
    BuiltInConfigurableColumn,
    ConfigurableColumn,
    FixedColumn,
} from 'products/logs/frontend/components/LogsViewer/columns/types'

export const SEVERITY_COLOR_COLUMN: FixedColumn = {
    id: 'severityColorColumn',
    type: 'severityColor',
    order: 0,
    width: 8,
    label: '',
}

export const SELECT_CHECKBOX_COLUMN: FixedColumn = {
    id: 'selectCheckboxColumn',
    type: 'selectCheckbox',
    order: 1,
    width: 28,
    label: '',
}

export const EXPAND_ROW_BUTTON_COLUMN: FixedColumn = {
    id: 'expandRowButtonColumn',
    type: 'expandRowButton',
    order: 2,
    width: 28,
    label: '',
}

export const FIXED_COLUMNS_BY_ID: Record<string, FixedColumn> = {
    severityColorColumn: SEVERITY_COLOR_COLUMN,
    selectCheckboxColumn: SELECT_CHECKBOX_COLUMN,
    expandRowButtonColumn: EXPAND_ROW_BUTTON_COLUMN,
}

export const TIMESTAMP_COLUMN: BuiltInConfigurableColumn = {
    id: 'timestampColumn',
    type: 'timestamp',
    order: 3,
    width: 180,
    label: 'Timestamp',
}

export const BODY_COLUMN: BuiltInConfigurableColumn = {
    id: 'bodyColumn',
    type: 'body',
    order: 4,
    width: 120,
    label: 'Body',
}

export const DATE_COLUMN: BuiltInConfigurableColumn = {
    id: 'dateColumn',
    type: 'date',
    width: 120,
    label: 'Date',
}

export const TIME_COLUMN: BuiltInConfigurableColumn = {
    id: 'timeColumn',
    type: 'time',
    width: 120,
    label: 'Time',
}

export const DISTINCT_ID_COLUMN: BuiltInConfigurableColumn = {
    id: 'distinctIdColumn',
    type: 'distinctId',
    width: 120,
    label: 'Distinct ID',
}

export const SESSION_ID_COLUMN: BuiltInConfigurableColumn = {
    id: 'sessionIdColumn',
    type: 'sessionId',
    width: 120,
    label: 'Session ID',
}

export const DEFAULT_CONFIGURABLE_COLUMNS_BY_ID: Record<string, ConfigurableColumn> = {
    timestampColumn: TIMESTAMP_COLUMN,
    bodyColumn: BODY_COLUMN,
}

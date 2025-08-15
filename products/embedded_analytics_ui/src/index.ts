// Main components
export { Overview } from './components/Overview'
export { Graph } from './components/Graph'
export { Table } from './components/Table'

// Types and schemas
export type { OverviewProps } from './components/Overview'

export type { GraphProps } from './components/Graph'

export type { TableProps } from './components/Table'

export type {
    OverviewResponse,
    GraphDataPoint,
    GraphResponse,
    TableColumn,
    TableRow,
    TableResponse,
    ErrorResponse,
} from './types/schemas'

export {
    OverviewResponseSchema,
    GraphDataPointSchema,
    GraphResponseSchema,
    TableColumnSchema,
    TableRowSchema,
    TableResponseSchema,
    ErrorResponseSchema,
} from './types/schemas'

// Utility functions
export { cn, formatNumber, formatChangePercentage, getTooltipContent, getChartColors } from './utils'

// Styles (consumers will need to import this)
import './styles/globals.css'

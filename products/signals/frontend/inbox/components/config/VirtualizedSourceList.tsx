import type { ReactElement } from 'react'
import { List, RowComponentProps, useDynamicRowHeight } from 'react-window'

import type { AgentRosterDefinition } from './agentRosterMeta'

const DEFAULT_ROW_HEIGHT = 68
const MAX_LIST_HEIGHT = 384

interface VirtualizedSourceListProps {
    sources: AgentRosterDefinition[]
    renderSource: (source: AgentRosterDefinition) => ReactElement
}

function SourceRow({
    ariaAttributes,
    index,
    style,
    sources,
    renderSource,
}: RowComponentProps<VirtualizedSourceListProps>): JSX.Element {
    return (
        <div
            {...ariaAttributes}
            style={style}
            className={index < sources.length - 1 ? 'border-b border-primary' : undefined}
        >
            {renderSource(sources[index])}
        </div>
    )
}

export function VirtualizedSourceList({ sources, renderSource }: VirtualizedSourceListProps): JSX.Element {
    const sourceIds = sources.map(({ source }) => source).join(',')
    const rowHeight = useDynamicRowHeight({ defaultRowHeight: DEFAULT_ROW_HEIGHT, key: sourceIds })
    const height = Math.min(
        MAX_LIST_HEIGHT,
        sources.reduce((total, _, index) => total + (rowHeight.getRowHeight(index) ?? DEFAULT_ROW_HEIGHT), 0)
    )

    return (
        <List
            key={sourceIds}
            aria-label="External sources"
            data-attr="signal-sources-list"
            defaultHeight={height}
            style={{ height }}
            rowComponent={SourceRow}
            rowCount={sources.length}
            rowHeight={rowHeight}
            rowProps={{ sources, renderSource }}
            overscanCount={2}
        />
    )
}

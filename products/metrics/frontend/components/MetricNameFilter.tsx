import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { metricNamePickerLogic } from './metricNamePickerLogic'

const ROW_HEIGHT = 44
const MAX_DROPDOWN_HEIGHT = 320
const DROPDOWN_WIDTH = 320

interface OptionRowData {
    items: { name: string; metric_type: string }[]
    selected: string
    onPick: (name: string) => void
}

function MetricOptionRow({
    index,
    style,
    items,
    selected,
    onPick,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & OptionRowData): JSX.Element {
    const item = items[index]
    const isSelected = selected === item.name
    return (
        <div style={style}>
            <LemonButton
                type={isSelected ? 'primary' : 'tertiary'}
                size="small"
                fullWidth
                onClick={() => onPick(item.name)}
                data-attr={`metrics-name-option-${item.name}`}
            >
                <div className="min-w-0 flex flex-col items-start gap-0.5 py-0.5">
                    <span className="truncate">{item.name}</span>
                    {item.metric_type && <span className="text-xs text-muted">{item.metric_type}</span>}
                </div>
            </LemonButton>
        </div>
    )
}

export interface MetricNameFilterProps {
    /** Currently selected metric name (empty string when nothing is picked). */
    value: string
    onChange: (name: string) => void
    /** Placeholder shown on the trigger when no metric is picked. */
    placeholder?: string
}

export const MetricNameFilter = ({
    value,
    onChange,
    placeholder = 'Pick a metric',
}: MetricNameFilterProps): JSX.Element => {
    return (
        <BindLogic logic={metricNamePickerLogic} props={{}}>
            <MetricNameFilterInner value={value} onChange={onChange} placeholder={placeholder} />
        </BindLogic>
    )
}

function MetricNameFilterInner({
    value,
    onChange,
    placeholder,
}: {
    value: string
    onChange: (name: string) => void
    placeholder: string
}): JSX.Element {
    const { items, itemsLoading, search } = useValues(metricNamePickerLogic)
    const { setSearch } = useActions(metricNamePickerLogic)

    const onPick = useCallback(
        (name: string) => {
            // Single-select: replace on pick. Multi-mode can be added later when
            // metrics-alerts arrives, mirroring ServiceFilter's selectionMode prop.
            onChange(value === name ? '' : name)
        },
        [value, onChange]
    )

    const rowProps = useMemo<OptionRowData>(() => ({ items, selected: value, onPick }), [items, value, onPick])

    const listHeight = useMemo(() => {
        const height = items.length * ROW_HEIGHT
        return Math.min(height, MAX_DROPDOWN_HEIGHT)
    }, [items.length])

    const selectedType = useMemo(() => items.find((item) => item.name === value)?.metric_type, [items, value])

    const triggerLabel = !value ? placeholder : selectedType ? `${value} (${selectedType})` : value

    return (
        <LemonDropdown
            closeOnClickInside
            overlay={
                <div className="space-y-px p-1">
                    <div className="px-1 pb-1">
                        <LemonInput
                            type="search"
                            placeholder="Search metrics..."
                            size="small"
                            fullWidth
                            value={search}
                            onChange={(val) => setSearch(val)}
                            autoFocus
                        />
                    </div>
                    {itemsLoading && items.length === 0 ? (
                        <div className="p-2 text-muted text-center text-xs">Loading metrics…</div>
                    ) : items.length === 0 ? (
                        <div className="p-2 text-muted text-center text-xs">
                            {search ? 'No metrics match this search.' : 'No metrics ingested in the last 7 days.'}
                        </div>
                    ) : (
                        <List<OptionRowData>
                            style={{ width: DROPDOWN_WIDTH, height: listHeight }}
                            rowCount={items.length}
                            rowHeight={ROW_HEIGHT}
                            overscanCount={5}
                            rowComponent={MetricOptionRow}
                            rowProps={rowProps}
                        />
                    )}
                </div>
            }
        >
            <LemonButton
                data-attr="metrics-name-filter"
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={itemsLoading && !value}
            >
                {triggerLabel}
            </LemonButton>
        </LemonDropdown>
    )
}

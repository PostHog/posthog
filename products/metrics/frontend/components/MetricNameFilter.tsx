import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, Spinner } from '@posthog/lemon-ui'

import { customMetricName, metricNamePickerLogic } from './metricNamePickerLogic'

const ROW_HEIGHT = 32
const MAX_DROPDOWN_HEIGHT = 320
const DROPDOWN_WIDTH = 320

interface OptionRowData {
    items: { name: string }[]
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
                <span className="truncate">{item.name}</span>
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
    disabled?: boolean
    disabledReason?: string | null
    /** Offer the typed name when the list does not have it, so a metric older than the list's 24 hours can be set. */
    allowCustomName?: boolean
}

export const MetricNameFilter = ({
    value,
    onChange,
    placeholder = 'Pick a metric',
    disabled,
    disabledReason,
    allowCustomName,
}: MetricNameFilterProps): JSX.Element => {
    return (
        <BindLogic logic={metricNamePickerLogic} props={{}}>
            <MetricNameFilterInner
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                disabled={disabled}
                disabledReason={disabledReason}
                allowCustomName={allowCustomName}
            />
        </BindLogic>
    )
}

function MetricNameFilterInner({
    value,
    onChange,
    placeholder,
    disabled,
    disabledReason,
    allowCustomName,
}: {
    value: string
    onChange: (name: string) => void
    placeholder: string
    disabled?: boolean
    disabledReason?: string | null
    allowCustomName?: boolean
}): JSX.Element {
    const { items, filteredItems, fullItemsLoading, searchedItemsLoading, scopeLoading, search } =
        useValues(metricNamePickerLogic)
    const { setSearch, openPicker } = useActions(metricNamePickerLogic)

    const onPick = useCallback(
        (name: string) => {
            // Single-select: replace on pick. Comparing several metrics is done with
            // clause rows (MetricsClauseRow), each holding its own picker.
            onChange(value === name ? '' : name)
        },
        [value, onChange]
    )

    const rowProps = useMemo<OptionRowData>(
        () => ({ items: filteredItems, selected: value, onPick }),
        [filteredItems, value, onPick]
    )

    const listHeight = useMemo(() => {
        const height = filteredItems.length * ROW_HEIGHT
        return Math.min(height, MAX_DROPDOWN_HEIGHT)
    }, [filteredItems.length])

    const triggerLabel = value || placeholder
    const customName = allowCustomName ? customMetricName(items, search) : null

    return (
        <LemonDropdown
            closeOnClickInside
            onVisibilityChange={(visible) => visible && openPicker()}
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
                            suffix={
                                searchedItemsLoading && search && filteredItems.length > 0 ? (
                                    <Spinner textColored />
                                ) : null
                            }
                            autoFocus
                        />
                    </div>
                    {(fullItemsLoading || searchedItemsLoading) && filteredItems.length === 0 ? (
                        <div className="p-2 text-muted text-center text-xs">
                            {search && !scopeLoading ? 'Searching…' : 'Loading metrics…'}
                        </div>
                    ) : filteredItems.length === 0 ? (
                        <div className="p-2 text-muted text-center text-xs">
                            {search ? 'No metrics match this search.' : 'No metrics ingested in the last 24 hours.'}
                        </div>
                    ) : (
                        <List<OptionRowData>
                            style={{ width: DROPDOWN_WIDTH, height: listHeight }}
                            rowCount={filteredItems.length}
                            rowHeight={ROW_HEIGHT}
                            overscanCount={5}
                            rowComponent={MetricOptionRow}
                            rowProps={rowProps}
                        />
                    )}
                    {customName ? (
                        <LemonButton
                            size="small"
                            fullWidth
                            onClick={() => onChange(customName)}
                            data-attr="metrics-name-filter-custom"
                        >
                            Use "{customName}"
                        </LemonButton>
                    ) : null}
                </div>
            }
        >
            <LemonButton
                data-attr="metrics-name-filter"
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={fullItemsLoading && !value && (items.length === 0 || scopeLoading)}
                disabled={disabled}
                disabledReason={disabledReason}
            >
                {triggerLabel}
            </LemonButton>
        </LemonDropdown>
    )
}

import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { DateRange, LogsQuery } from '~/queries/schema/schema-general'

import { serviceFilterLogic, ServiceFilterLogicProps } from './serviceFilterLogic'

const SERVICE_OPTION_HEIGHT = 33
const MAX_DROPDOWN_HEIGHT = 300
const DROPDOWN_WIDTH = 300

interface ServiceOptionRowProps {
    serviceNames: string[]
    selected: string[]
    onToggle: (name: string) => void
}

function ServiceOptionRow({
    index,
    style,
    serviceNames: names,
    selected,
    onToggle,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & ServiceOptionRowProps): JSX.Element {
    const name = names[index]
    const isSelected = selected.includes(name)
    return (
        <div style={style}>
            <LemonButton
                type="tertiary"
                size="small"
                fullWidth
                icon={<LemonCheckbox checked={isSelected} className="pointer-events-none" />}
                onClick={() => onToggle(name)}
                data-attr={`logs-service-option-${name}`}
            >
                {name}
            </LemonButton>
        </div>
    )
}

interface ServiceFilterProps {
    value: LogsQuery['serviceNames']
    onChange: (serviceNames: LogsQuery['serviceNames']) => void
    /** When omitted, the backend's default date range is used */
    dateRange?: DateRange
    /** Single-select replaces the selection on each pick; omit for multi-select (logs viewer). */
    selectionMode?: 'multi' | 'single'
    /** Button label when nothing is selected (single mode only). */
    emptyButtonLabel?: string
}

export const ServiceFilter = ({
    value,
    onChange,
    dateRange,
    selectionMode = 'multi',
    emptyButtonLabel = 'Pick service',
}: ServiceFilterProps): JSX.Element => {
    const logicProps: ServiceFilterLogicProps = { dateRange }

    return (
        <BindLogic logic={serviceFilterLogic} props={logicProps}>
            <ServiceFilterInner
                value={value}
                onChange={onChange}
                selectionMode={selectionMode}
                emptyButtonLabel={emptyButtonLabel}
            />
        </BindLogic>
    )
}

function ServiceFilterInner({
    value,
    onChange,
    selectionMode,
    emptyButtonLabel,
}: {
    value: LogsQuery['serviceNames']
    onChange: (serviceNames: LogsQuery['serviceNames']) => void
    selectionMode: 'multi' | 'single'
    emptyButtonLabel: string
}): JSX.Element {
    const { serviceNames, allServiceNames, allServiceNamesLoading, search } = useValues(serviceFilterLogic)
    const { setSearch } = useActions(serviceFilterLogic)

    const selected = value ?? []

    const onToggle = useCallback(
        (name: string) => {
            if (selectionMode === 'single') {
                const isSelected = selected.includes(name)
                onChange(isSelected ? [] : [name])
                return
            }
            const isSelected = selected.includes(name)
            const newNames = isSelected ? selected.filter((n) => n !== name) : [...selected, name]
            onChange(newNames)
        },
        [selected, onChange, selectionMode]
    )

    const rowProps = useMemo<ServiceOptionRowProps>(
        () => ({ serviceNames, selected, onToggle }),
        [serviceNames, selected, onToggle]
    )

    const listHeight = useMemo(() => {
        const height = serviceNames.length * SERVICE_OPTION_HEIGHT
        return Math.min(height, MAX_DROPDOWN_HEIGHT)
    }, [serviceNames.length])

    return (
        <LemonDropdown
            closeOnClickInside={selectionMode === 'single'}
            overlay={
                <div className="space-y-px p-1">
                    <div className="px-1 pb-1">
                        <LemonInput
                            type="search"
                            placeholder="Search services..."
                            size="small"
                            fullWidth
                            value={search}
                            onChange={(val) => setSearch(val)}
                            autoFocus
                        />
                    </div>
                    <div>
                        {allServiceNamesLoading && allServiceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">Loading...</div>
                        ) : serviceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">
                                {search ? 'No matching services' : 'No services found'}
                            </div>
                        ) : (
                            <>
                                {selected.length > 0 && selectionMode === 'multi' && (
                                    <>
                                        <div className="flex flex-wrap gap-1 px-1 pb-1 max-w-[300px]">
                                            {selected.map((name: string) => (
                                                <LemonTag
                                                    key={`selected-${name}`}
                                                    type="highlight"
                                                    closable
                                                    size="small"
                                                    onClose={() => {
                                                        onChange(selected.filter((n) => n !== name))
                                                    }}
                                                >
                                                    {name}
                                                </LemonTag>
                                            ))}
                                        </div>
                                        <div className="border-b border-border my-1" />
                                    </>
                                )}
                                <List<ServiceOptionRowProps>
                                    style={{ width: DROPDOWN_WIDTH, height: listHeight }}
                                    rowCount={serviceNames.length}
                                    rowHeight={SERVICE_OPTION_HEIGHT}
                                    overscanCount={5}
                                    rowComponent={ServiceOptionRow}
                                    rowProps={rowProps}
                                />
                            </>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                data-attr="logs-service-filter"
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={allServiceNamesLoading && selected.length === 0}
            >
                {selected.length === 0
                    ? selectionMode === 'single'
                        ? emptyButtonLabel
                        : 'All services'
                    : selected.length === 1
                      ? selected[0]
                      : `${selected.length} services`}
            </LemonButton>
        </LemonDropdown>
    )
}

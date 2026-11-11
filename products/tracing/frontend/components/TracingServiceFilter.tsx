import { BindLogic, useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { DateRange } from '~/queries/schema/schema-general'

import { tracingServiceFilterLogic, TracingServiceFilterLogicProps } from '../tracingServiceFilterLogic'

interface TracingServiceFilterProps {
    value: string[]
    onChange: (serviceNames: string[]) => void
    dateRange?: DateRange
}

export function TracingServiceFilter({ value, onChange, dateRange }: TracingServiceFilterProps): JSX.Element {
    const logicProps: TracingServiceFilterLogicProps = { dateRange }

    return (
        <BindLogic logic={tracingServiceFilterLogic} props={logicProps}>
            <TracingServiceFilterInner value={value} onChange={onChange} />
        </BindLogic>
    )
}

function TracingServiceFilterInner({
    value,
    onChange,
}: {
    value: string[]
    onChange: (serviceNames: string[]) => void
}): JSX.Element {
    const { serviceNames, allServiceNames, allServiceNamesLoading, search } = useValues(tracingServiceFilterLogic)
    const { setSearch } = useActions(tracingServiceFilterLogic)

    const selected = value ?? []

    return (
        <LemonDropdown
            closeOnClickInside={false}
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
                    <div className="max-h-[300px] overflow-y-auto">
                        {allServiceNamesLoading && allServiceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">Loading...</div>
                        ) : serviceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">
                                {search ? 'No matching services' : 'No services found'}
                            </div>
                        ) : (
                            <>
                                {selected.length > 0 && (
                                    <>
                                        <div className="flex flex-wrap gap-1 px-1 pb-1 max-w-[300px]">
                                            {selected.map((name: string) => (
                                                <LemonTag
                                                    key={`selected-${name}`}
                                                    type="highlight"
                                                    closable
                                                    size="small"
                                                    onClose={() => onChange(selected.filter((n) => n !== name))}
                                                >
                                                    {name}
                                                </LemonTag>
                                            ))}
                                        </div>
                                        <div className="border-b border-border my-1" />
                                    </>
                                )}
                                {serviceNames.map((name: string) => {
                                    const isSelected = selected.includes(name)
                                    return (
                                        <LemonButton
                                            key={name}
                                            type="tertiary"
                                            size="small"
                                            fullWidth
                                            icon={
                                                <LemonCheckbox checked={isSelected} className="pointer-events-none" />
                                            }
                                            onClick={() => {
                                                const newNames = isSelected
                                                    ? selected.filter((n) => n !== name)
                                                    : [...selected, name]
                                                onChange(newNames)
                                            }}
                                        >
                                            {name}
                                        </LemonButton>
                                    )
                                })}
                            </>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                data-attr="tracing-service-filter"
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={allServiceNamesLoading && selected.length === 0}
            >
                {selected.length === 0
                    ? 'All services'
                    : selected.length === 1
                      ? selected[0]
                      : `${selected.length} services`}
            </LemonButton>
        </LemonDropdown>
    )
}

import { BindLogic, useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { DateRange, LogsQuery } from '~/queries/schema/schema-general'

import { serviceFilterLogic, ServiceFilterLogicProps } from './serviceFilterLogic'

interface ServiceFilterProps {
    value: LogsQuery['serviceNames']
    onChange: (serviceNames: LogsQuery['serviceNames']) => void
    /** When omitted, the backend's default date range is used */
    dateRange?: DateRange
}

export const ServiceFilter = ({ value, onChange, dateRange }: ServiceFilterProps): JSX.Element => {
    const logicProps: ServiceFilterLogicProps = { dateRange }

    return (
        <BindLogic logic={serviceFilterLogic} props={logicProps}>
            <ServiceFilterInner value={value} onChange={onChange} />
        </BindLogic>
    )
}

function ServiceFilterInner({
    value,
    onChange,
}: {
    value: LogsQuery['serviceNames']
    onChange: (serviceNames: LogsQuery['serviceNames']) => void
}): JSX.Element {
    const { serviceNames, allServiceNames, allServiceNamesLoading, search } = useValues(serviceFilterLogic)
    const { setSearch } = useActions(serviceFilterLogic)

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
                            serviceNames.map((name: string) => (
                                <LemonButton
                                    key={name}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    icon={
                                        <LemonCheckbox
                                            checked={selected.includes(name)}
                                            className="pointer-events-none"
                                        />
                                    }
                                    onClick={() => {
                                        const newNames = selected.includes(name)
                                            ? selected.filter((n) => n !== name)
                                            : [...selected, name]
                                        onChange(newNames)
                                    }}
                                    data-attr={`logs-service-option-${name}`}
                                >
                                    {name}
                                </LemonButton>
                            ))
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
                    ? 'All services'
                    : selected.length === 1
                      ? selected[0]
                      : `${selected.length} services`}
            </LemonButton>
        </LemonDropdown>
    )
}

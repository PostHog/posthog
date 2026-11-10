import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
} from '@posthog/quill'

import type { EmailDeliveryStatusEnumApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailLogDateFilter } from './TransactionalEmailLogDateFilter'
import { transactionalEmailLogLogic } from './transactionalEmailLogLogic'

const ANY = 'any'

export function QuillTransactionalEmailLogFilters({
    emailOptions,
    statusOptions,
}: {
    emailOptions: readonly FilterOption[]
    statusOptions: readonly FilterOption<EmailDeliveryStatusEnumApi>[]
}): JSX.Element {
    const { filters, pageLoading } = useValues(transactionalEmailLogLogic)
    const { setFilters, refresh } = useActions(transactionalEmailLogLogic)
    const menuFiltersOn = filters.workflowId !== null || filters.status !== null

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="flex-1 min-w-60">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>
                        <IconSearch />
                    </InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    aria-label="Search by recipient or message ID"
                    placeholder="Search by recipient or message ID"
                    value={filters.search}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                        setFilters({ search: event.target.value })
                    }
                    data-attr="transactional-email-log-search"
                />
            </InputGroup>
            <DropdownMenu>
                <FilterMenuTrigger active={menuFiltersOn} dataAttr="transactional-email-log-filter-menu" />
                <DropdownMenuContent align="start" className="min-w-64">
                    <FilterRadioSubMenu
                        label="Email"
                        options={[{ value: ANY, label: 'All emails' }, ...emailOptions]}
                        value={filters.workflowId ?? ANY}
                        defaultValue={ANY}
                        onChange={(value) => setFilters({ workflowId: value === ANY ? null : value })}
                        dataAttr="transactional-email-log-email-filter"
                    />
                    <FilterRadioSubMenu<EmailDeliveryStatusEnumApi | typeof ANY>
                        label="Status"
                        options={[{ value: ANY, label: 'Any status' }, ...statusOptions]}
                        value={filters.status ?? ANY}
                        defaultValue={ANY}
                        onChange={(value) => setFilters({ status: value === ANY ? null : value })}
                        dataAttr="transactional-email-log-status-filter"
                    />
                    <FilterClearItem
                        active={menuFiltersOn}
                        onClear={() => setFilters({ workflowId: null, status: null })}
                        dataAttr="transactional-email-log-clear-filters"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
            <TransactionalEmailLogDateFilter />
            <Button
                variant="outline"
                loading={pageLoading}
                onClick={() => refresh()}
                data-attr="transactional-email-log-refresh"
            >
                <IconRefresh />
                Refresh
            </Button>
        </div>
    )
}

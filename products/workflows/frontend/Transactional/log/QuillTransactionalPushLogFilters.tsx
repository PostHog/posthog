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

import type { PushSendStatusEnumApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailLogDateFilter } from './TransactionalEmailLogDateFilter'
import { TransactionalLogChannelSubMenu } from './TransactionalLogChannelSubMenu'
import { transactionalPushLogLogic } from './transactionalPushLogLogic'

const ANY = 'any'

export function QuillTransactionalPushLogFilters({
    pushOptions,
    statusOptions,
}: {
    pushOptions: readonly FilterOption[]
    statusOptions: readonly FilterOption<PushSendStatusEnumApi>[]
}): JSX.Element {
    const { filters, pageLoading } = useValues(transactionalPushLogLogic)
    const { setFilters, refresh } = useActions(transactionalPushLogLogic)
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
                    aria-label="Search by distinct ID"
                    placeholder="Search by distinct ID"
                    value={filters.search}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                        setFilters({ search: event.target.value })
                    }
                    data-attr="transactional-push-log-search"
                />
            </InputGroup>
            <DropdownMenu>
                <FilterMenuTrigger active={menuFiltersOn} dataAttr="transactional-push-log-filter-menu" />
                <DropdownMenuContent align="start" className="min-w-64">
                    <TransactionalLogChannelSubMenu />
                    <FilterRadioSubMenu
                        label="Push notification"
                        options={[{ value: ANY, label: 'All push notifications' }, ...pushOptions]}
                        value={filters.workflowId ?? ANY}
                        defaultValue={ANY}
                        onChange={(value) => setFilters({ workflowId: value === ANY ? null : value })}
                        dataAttr="transactional-push-log-push-filter"
                    />
                    <FilterRadioSubMenu<PushSendStatusEnumApi | typeof ANY>
                        label="Status"
                        options={[{ value: ANY, label: 'Any status' }, ...statusOptions]}
                        value={filters.status ?? ANY}
                        defaultValue={ANY}
                        onChange={(value) => setFilters({ status: value === ANY ? null : value })}
                        dataAttr="transactional-push-log-status-filter"
                    />
                    <FilterClearItem
                        active={menuFiltersOn}
                        onClear={() => setFilters({ workflowId: null, status: null })}
                        dataAttr="transactional-push-log-clear-filters"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
            <TransactionalEmailLogDateFilter />
            <Button
                variant="outline"
                loading={pageLoading}
                onClick={() => refresh()}
                data-attr="transactional-push-log-refresh"
            >
                <IconRefresh />
                Refresh
            </Button>
        </div>
    )
}

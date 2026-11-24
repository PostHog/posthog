import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Button, Card, DataTable, type DataTableProps } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { formatPercentage } from 'lib/utils/numbers'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { InstrumentationEmptyState } from '../components/InstrumentationEmptyState'
import { McpDateFilter } from '../components/McpDateFilter'
import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { TableLoadingBar } from '../components/TableLoadingBar'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLabel } from '../dashboard/HarnessLabel'
import { SkeletonLine } from '../dashboard/SkeletonLine'
import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { mcpUsersLogic } from './mcpUsersLogic'
import { UserReport } from './UserReport'
import { userReportLogic } from './userReportLogic'
import type { UserRow } from './usersQueries'

export function mcpUserUrl(distinctId: string, dateFrom: string | null, dateTo: string | null): string {
    return combineUrl(urls.mcpAnalyticsUser(distinctId), {
        date_from: dateFrom ?? undefined,
        date_to: dateTo ?? undefined,
    }).url
}

const errorRate = (user: UserRow): number => (user.calls ? (user.errors / user.calls) * 100 : 0)

const USER_COLUMNS: DataTableProps<UserRow, unknown>['columns'] = [
    {
        id: 'user',
        header: 'User',
        accessorFn: (user) => user.label,
        meta: { expand: true },
        cell: ({ row: { original: user } }) => (
            <PersonDisplay
                person={{
                    distinct_id: user.distinctId,
                    properties: user.label !== user.distinctId ? { email: user.label } : {},
                }}
                withIcon
                noLink
                noPopover
            />
        ),
    },
    {
        id: 'calls',
        header: 'Calls',
        accessorFn: (user) => user.calls,
        meta: { align: 'right' },
        cell: ({ row }) => formatNumber(row.original.calls),
    },
    {
        id: 'sessions',
        header: 'Sessions',
        accessorFn: (user) => user.sessions,
        meta: { align: 'right' },
        cell: ({ row }) => formatNumber(row.original.sessions),
    },
    {
        id: 'errorRate',
        header: 'Error rate',
        accessorFn: errorRate,
        meta: { align: 'right' },
        cell: ({ row }) => formatPercentage(errorRate(row.original), { compact: true }),
    },
    {
        id: 'p95',
        header: 'p95',
        accessorFn: (user) => user.p95Ms ?? 0,
        meta: { align: 'right' },
        cell: ({ row }) => (row.original.p95Ms !== null ? formatMs(row.original.p95Ms) : '–'),
    },
    {
        id: 'topTool',
        header: 'Top tool',
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono">{row.original.topTool}</span>,
    },
    {
        id: 'topHarness',
        header: 'Harness',
        enableSorting: false,
        cell: ({ row }) => (
            <span className="whitespace-nowrap">
                <HarnessLabel category={row.original.topHarness} />
            </span>
        ),
    },
    {
        id: 'lastSeen',
        header: 'Last seen',
        accessorFn: (user) => user.lastSeen,
        meta: { align: 'right' },
        cell: ({ row }) => <TZLabel time={row.original.lastSeen} />,
    },
]

const USERS_PAGE_SIZE = 50

function UsersTable(): JSX.Element {
    const { users, filteredUsers, usersLoading, usersFailed, search, openedUser } = useValues(mcpUsersLogic)
    const { openUser, loadUsers } = useActions(mcpUsersLogic)
    const [shownCount, setShownCount] = useState(USERS_PAGE_SIZE)
    useEffect(() => setShownCount(USERS_PAGE_SIZE), [filteredUsers])

    if (!usersLoading && !usersFailed && users.length === 0) {
        return (
            <div data-quill>
                <InstrumentationEmptyState fix={INSTRUMENTATION_FIXES.identify} dataAttr="mcp-users-setup" />
            </div>
        )
    }
    return (
        <>
            {usersFailed ? (
                <LemonBanner type="error">
                    <div className="flex items-center justify-between gap-2">
                        Couldn't load users.
                        <LemonButton type="secondary" size="small" onClick={() => loadUsers()}>
                            Try again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : null}
            {/* pt-0: no card header. */}
            <Card size="sm" className="gap-0 overflow-hidden pt-0" data-attr="mcp-users-table">
                <div className="relative">
                    <DataTable
                        columns={USER_COLUMNS}
                        // Rows arrive sorted by calls.
                        data={filteredUsers.slice(0, shownCount)}
                        fullWidth
                        size="sm"
                        stickyHeader
                        className="max-h-[44rem]"
                        getRowId={(user) => user.distinctId}
                        // Marks the open user's row the way Tool quality marks its open tool.
                        rowSelection={openedUser ? { [openedUser]: true } : {}}
                        onRowClick={(user) => openUser(user.distinctId)}
                        empty={
                            usersLoading ? (
                                <div className="flex flex-col gap-2 py-2">
                                    <SkeletonLine className="w-1/2" />
                                    <SkeletonLine className="w-1/3" />
                                </div>
                            ) : (
                                <span className="text-secondary">
                                    {search ? 'No users match this search.' : 'No users in this date range.'}
                                </span>
                            )
                        }
                    />
                    <TableLoadingBar loading={usersLoading && filteredUsers.length > 0} />
                </div>
            </Card>
            {filteredUsers.length > shownCount ? (
                <div className="flex justify-center" data-quill>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShownCount(shownCount + USERS_PAGE_SIZE)}
                        data-attr="mcp-users-load-more"
                    >
                        Load more
                    </Button>
                </div>
            ) : null}
        </>
    )
}

/** The Users tab: who calls the server, with each user's usage in a drawer. */
export function MCPAnalyticsUsers(): JSX.Element {
    const { dateFilter, search, usersLoading, openedUser, openedPosition, previousUser, nextUser, users } =
        useValues(mcpUsersLogic)
    const { setDateFilter, setSearch, loadUsers, openUser } = useActions(mcpUsersLogic)
    const openedLabel = users.find((user) => user.distinctId === openedUser)?.label ?? openedUser

    return (
        <div className="flex flex-col gap-4">
            <McpSharedFilters
                pageKey="mcp-users"
                dataAttrPrefix="mcp-users"
                onRefresh={loadUsers}
                refreshing={usersLoading}
                hasPageFilters={!!search}
                onClearPageFilters={() => setSearch('')}
            >
                <AnalyticsSearchInput
                    value={search}
                    onChange={setSearch}
                    label="Search users"
                    placeholder="Search users"
                    dataAttr="mcp-users-search"
                    className="max-w-64 min-w-32 flex-[1_1_8rem]"
                />
                <McpDateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDateFilter}
                    dataAttr="mcp-users-date-filter"
                />
            </McpSharedFilters>
            <UsersTable />
            {openedUser ? (
                <MCPDetailDrawer
                    noun="user"
                    title={<span className="ph-no-capture">{openedLabel}</span>}
                    position={openedPosition}
                    onPrevious={previousUser ? () => openUser(previousUser) : null}
                    onNext={nextUser ? () => openUser(nextUser) : null}
                    fullPageHref={mcpUserUrl(openedUser, dateFilter.dateFrom, dateFilter.dateTo)}
                    onClose={() => openUser(null)}
                    data-attr="mcp-users-drawer"
                >
                    <BindLogic
                        logic={userReportLogic}
                        props={{ distinctId: openedUser, dateFrom: dateFilter.dateFrom, dateTo: dateFilter.dateTo }}
                    >
                        <div data-quill>
                            <UserReport />
                        </div>
                    </BindLogic>
                </MCPDetailDrawer>
            ) : null}
        </div>
    )
}

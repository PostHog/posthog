import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { formatPercentage } from 'lib/utils/numbers'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { InstrumentationEmptyState } from '../components/InstrumentationEmptyState'
import { McpDateFilter } from '../components/McpDateFilter'
import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLabel } from '../dashboard/HarnessLabel'
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

function UsersTable(): JSX.Element {
    const { users, filteredUsers, usersLoading, usersFailed, search, openedUser } = useValues(mcpUsersLogic)
    const { openUser, loadUsers } = useActions(mcpUsersLogic)

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
            <LemonTable<UserRow>
                dataSource={filteredUsers}
                loading={usersLoading}
                rowKey="distinctId"
                defaultSorting={{ columnKey: 'calls', order: -1 }}
                emptyState={search ? 'No users match this search.' : 'No users in this date range.'}
                onRow={(user) => ({
                    onClick: () => openUser(user.distinctId),
                    className: 'cursor-pointer',
                    'data-attr': 'mcp-users-row',
                })}
                rowStatus={(user) => (user.distinctId === openedUser ? 'highlighted' : null)}
                columns={[
                    {
                        title: 'User',
                        key: 'user',
                        sorter: (a, b) => a.label.localeCompare(b.label),
                        render: (_, user) => (
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
                        title: 'Calls',
                        key: 'calls',
                        align: 'right',
                        sorter: (a, b) => a.calls - b.calls,
                        render: (_, user) => formatNumber(user.calls),
                    },
                    {
                        title: 'Sessions',
                        key: 'sessions',
                        align: 'right',
                        sorter: (a, b) => a.sessions - b.sessions,
                        render: (_, user) => formatNumber(user.sessions),
                    },
                    {
                        title: 'Error rate',
                        key: 'errorRate',
                        align: 'right',
                        sorter: (a, b) => errorRate(a) - errorRate(b),
                        render: (_, user) => formatPercentage(errorRate(user), { compact: true }),
                    },
                    {
                        title: 'p95',
                        key: 'p95',
                        align: 'right',
                        sorter: (a, b) => (a.p95Ms ?? 0) - (b.p95Ms ?? 0),
                        render: (_, user) => (user.p95Ms !== null ? formatMs(user.p95Ms) : '–'),
                    },
                    {
                        title: 'Top tool',
                        key: 'topTool',
                        render: (_, user) => <span className="font-mono">{user.topTool}</span>,
                    },
                    {
                        title: 'Harness',
                        key: 'topHarness',
                        render: (_, user) => <HarnessLabel category={user.topHarness} />,
                    },
                    {
                        title: 'Last seen',
                        key: 'lastSeen',
                        align: 'right',
                        sorter: (a, b) => a.lastSeen.localeCompare(b.lastSeen),
                        render: (_, user) => <TZLabel time={user.lastSeen} />,
                    },
                ]}
            />
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
                    title={openedLabel}
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

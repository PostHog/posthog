import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import {
    Card,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { formatPercentage } from 'lib/utils/numbers'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { InstrumentationEmptyState } from '../components/InstrumentationEmptyState'
import { McpDateFilter } from '../components/McpDateFilter'
import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLabel } from '../dashboard/HarnessLabel'
import { SkeletonLine } from '../dashboard/SkeletonLine'
import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { mcpUsersLogic } from './mcpUsersLogic'
import { UserReport } from './UserReport'
import { userReportLogic } from './userReportLogic'

export function mcpUserUrl(distinctId: string, dateFrom: string | null, dateTo: string | null): string {
    return combineUrl(urls.mcpAnalyticsUser(distinctId), {
        date_from: dateFrom ?? undefined,
        date_to: dateTo ?? undefined,
    }).url
}

const COLUMNS = ['Calls', 'Sessions', 'Error rate', 'p95', 'Top tool', 'Harness', 'Last seen']

function UsersTable(): JSX.Element {
    const { users, filteredUsers, usersLoading, usersFailed, search, openedUser } = useValues(mcpUsersLogic)
    const { openUser, loadUsers } = useActions(mcpUsersLogic)

    if (!usersLoading && !usersFailed && users.length === 0) {
        return (
            <Card size="sm">
                <InstrumentationEmptyState fix={INSTRUMENTATION_FIXES.identify} dataAttr="mcp-users-setup" />
            </Card>
        )
    }
    return (
        // pt-0: no card header.
        <Card size="sm" className="gap-0 overflow-hidden pt-0">
            <Table fullWidth stickyHeader className="max-h-[44rem]" aria-busy={usersLoading}>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>User</TableHead>
                        {COLUMNS.map((column) => (
                            <TableHead
                                key={column}
                                align={column === 'Top tool' || column === 'Harness' ? 'left' : 'right'}
                            >
                                {column}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                {usersLoading && users.length === 0 ? (
                    <TableBody>
                        {[0, 1, 2, 3, 4].map((i) => (
                            <TableRow key={i}>
                                <TableCell expand>
                                    <SkeletonLine className="w-48" />
                                </TableCell>
                                {COLUMNS.map((column) => (
                                    <TableCell key={column}>
                                        <SkeletonLine className="w-12" />
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                ) : usersFailed ? (
                    <TableEmpty className="py-6 text-secondary">
                        Couldn't load users.{' '}
                        <button type="button" className="underline" onClick={() => loadUsers()}>
                            Try again
                        </button>
                    </TableEmpty>
                ) : filteredUsers.length === 0 ? (
                    <TableEmpty className="py-6 text-secondary">
                        {search ? 'No users match this search.' : 'No users in this date range.'}
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {filteredUsers.map((user) => (
                            <TableRow
                                key={user.distinctId}
                                className={cn(
                                    'cursor-pointer',
                                    user.distinctId === openedUser && 'bg-fill-highlight-100'
                                )}
                                onClick={() => openUser(user.distinctId)}
                                data-attr="mcp-users-row"
                            >
                                <TableCell expand>
                                    <div className="truncate font-medium">{user.label}</div>
                                    {user.label !== user.distinctId ? (
                                        <div className="truncate text-xs text-secondary">{user.distinctId}</div>
                                    ) : null}
                                </TableCell>
                                <TableCell align="right">{formatNumber(user.calls)}</TableCell>
                                <TableCell align="right">{formatNumber(user.sessions)}</TableCell>
                                <TableCell align="right">
                                    {formatPercentage(user.calls ? (user.errors / user.calls) * 100 : 0, {
                                        compact: true,
                                    })}
                                </TableCell>
                                <TableCell align="right">{user.p95Ms !== null ? formatMs(user.p95Ms) : '–'}</TableCell>
                                <TableCell>
                                    <span className="font-mono">{user.topTool}</span>
                                </TableCell>
                                <TableCell>
                                    <HarnessLabel category={user.topHarness} />
                                </TableCell>
                                <TableCell align="right" className="whitespace-nowrap">
                                    <TZLabel time={user.lastSeen} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
        </Card>
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
            <div data-quill>
                <UsersTable />
            </div>
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

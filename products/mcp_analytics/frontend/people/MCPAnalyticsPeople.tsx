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
import { mcpPeopleLogic } from './mcpPeopleLogic'
import { PersonReport } from './PersonReport'
import { personReportLogic } from './personReportLogic'

export function mcpPersonUrl(distinctId: string, dateFrom: string | null, dateTo: string | null): string {
    return combineUrl(urls.mcpAnalyticsPerson(distinctId), {
        date_from: dateFrom ?? undefined,
        date_to: dateTo ?? undefined,
    }).url
}

const COLUMNS = ['Calls', 'Sessions', 'Error rate', 'p95', 'Top tool', 'Harness', 'Last seen']

function PeopleTable(): JSX.Element {
    const { people, filteredPeople, peopleLoading, peopleFailed, search, openedPerson } = useValues(mcpPeopleLogic)
    const { openPerson, loadPeople } = useActions(mcpPeopleLogic)

    if (!peopleLoading && !peopleFailed && people.length === 0) {
        return (
            <Card size="sm">
                <InstrumentationEmptyState fix={INSTRUMENTATION_FIXES.identify} dataAttr="mcp-people-setup" />
            </Card>
        )
    }
    return (
        // pt-0: no card header.
        <Card size="sm" className="gap-0 overflow-hidden pt-0">
            <Table fullWidth stickyHeader className="max-h-[44rem]" aria-busy={peopleLoading}>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Person</TableHead>
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
                {peopleLoading && people.length === 0 ? (
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
                ) : peopleFailed ? (
                    <TableEmpty className="py-6 text-secondary">
                        Couldn't load people.{' '}
                        <button type="button" className="underline" onClick={() => loadPeople()}>
                            Try again
                        </button>
                    </TableEmpty>
                ) : filteredPeople.length === 0 ? (
                    <TableEmpty className="py-6 text-secondary">
                        {search ? 'No people match this search.' : 'No people in this date range.'}
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {filteredPeople.map((person) => (
                            <TableRow
                                key={person.distinctId}
                                className={cn(
                                    'cursor-pointer',
                                    person.distinctId === openedPerson && 'bg-fill-highlight-100'
                                )}
                                onClick={() => openPerson(person.distinctId)}
                                data-attr="mcp-people-row"
                            >
                                <TableCell expand>
                                    <div className="truncate font-medium">{person.label}</div>
                                    {person.label !== person.distinctId ? (
                                        <div className="truncate text-xs text-secondary">{person.distinctId}</div>
                                    ) : null}
                                </TableCell>
                                <TableCell align="right">{formatNumber(person.calls)}</TableCell>
                                <TableCell align="right">{formatNumber(person.sessions)}</TableCell>
                                <TableCell align="right">
                                    {formatPercentage(person.calls ? (person.errors / person.calls) * 100 : 0, {
                                        compact: true,
                                    })}
                                </TableCell>
                                <TableCell align="right">
                                    {person.p95Ms !== null ? formatMs(person.p95Ms) : '–'}
                                </TableCell>
                                <TableCell>
                                    <span className="font-mono">{person.topTool}</span>
                                </TableCell>
                                <TableCell>
                                    <HarnessLabel category={person.topHarness} />
                                </TableCell>
                                <TableCell align="right" className="whitespace-nowrap">
                                    <TZLabel time={person.lastSeen} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
        </Card>
    )
}

/** The People tab: who calls the server, with each person's usage in a drawer. */
export function MCPAnalyticsPeople(): JSX.Element {
    const { dateFilter, search, peopleLoading, openedPerson, openedPosition, previousPerson, nextPerson, people } =
        useValues(mcpPeopleLogic)
    const { setDateFilter, setSearch, loadPeople, openPerson } = useActions(mcpPeopleLogic)
    const openedLabel = people.find((person) => person.distinctId === openedPerson)?.label ?? openedPerson

    return (
        <div className="flex flex-col gap-4">
            <McpSharedFilters
                pageKey="mcp-people"
                dataAttrPrefix="mcp-people"
                onRefresh={loadPeople}
                refreshing={peopleLoading}
                hasPageFilters={!!search}
                onClearPageFilters={() => setSearch('')}
            >
                <AnalyticsSearchInput
                    value={search}
                    onChange={setSearch}
                    label="Search people"
                    placeholder="Search people"
                    dataAttr="mcp-people-search"
                    className="max-w-64 min-w-32 flex-[1_1_8rem]"
                />
                <McpDateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDateFilter}
                    dataAttr="mcp-people-date-filter"
                />
            </McpSharedFilters>
            <div data-quill>
                <PeopleTable />
            </div>
            {openedPerson ? (
                <MCPDetailDrawer
                    noun="person"
                    title={openedLabel}
                    position={openedPosition}
                    onPrevious={previousPerson ? () => openPerson(previousPerson) : null}
                    onNext={nextPerson ? () => openPerson(nextPerson) : null}
                    fullPageHref={mcpPersonUrl(openedPerson, dateFilter.dateFrom, dateFilter.dateTo)}
                    onClose={() => openPerson(null)}
                    data-attr="mcp-people-drawer"
                >
                    <BindLogic
                        logic={personReportLogic}
                        props={{ distinctId: openedPerson, dateFrom: dateFilter.dateFrom, dateTo: dateFilter.dateTo }}
                    >
                        <div data-quill>
                            <PersonReport />
                        </div>
                    </BindLogic>
                </MCPDetailDrawer>
            ) : null}
        </div>
    )
}

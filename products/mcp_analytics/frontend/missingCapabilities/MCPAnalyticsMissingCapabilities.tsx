import { useActions, useValues } from 'kea'

import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import { IconBook, IconMCP } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { MCPMissingCapabilitiesItem } from '~/queries/schema/schema-general'

import { McpDateFilter } from '../components/McpDateFilter'
import { HarnessLogo } from '../dashboard/harness'
import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import { isUnidentifiedClient, mcpMissingCapabilitiesLogic, parsePersonProperties } from './mcpMissingCapabilitiesLogic'
import { MissingCapabilitiesPreview } from './MissingCapabilitiesPreview'

const MISSING_CAPABILITY_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/missing-capability'
const ACCENT_TEXT = 'text-[var(--empty-state-accent)] dark:text-[var(--empty-state-accent-dark)]'

const HedgehogPuzzle = pngHoggie(puzzlePng)

function FilterBar(): JSX.Element {
    const { search, dateFilter } = useValues(mcpMissingCapabilitiesLogic)
    const { setSearch, setDateFilter } = useActions(mcpMissingCapabilitiesLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                type="search"
                placeholder="Search what agents asked for"
                value={search}
                onChange={setSearch}
                className="min-w-60 flex-1"
                data-attr="mcp-missing-capabilities-search"
            />
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                dataAttr="mcp-missing-capabilities-date-filter"
            />
        </div>
    )
}

/**
 * This tab is already inside a configured product, so it cannot use the scene-level setup gate.
 * An empty date range keeps the filters visible and explains how to enable report collection.
 */
function NoReportsState(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()

    return (
        <div
            className="grid w-full grid-cols-1 items-center gap-8 py-4 md:grid-cols-[minmax(0,1fr)_40%]"
            style={
                {
                    '--empty-state-accent': 'var(--color-product-mcp-analytics-light)',
                    '--empty-state-accent-dark': 'var(--color-product-mcp-analytics-dark)',
                } as React.CSSProperties
            }
            data-attr="mcp-missing-capabilities-empty"
        >
            <div className="flex min-w-0 flex-col gap-4">
                <div className="flex items-start gap-4">
                    <HedgehogPuzzle className="hidden w-24 shrink-0 sm:block" />
                    <div className="flex flex-col gap-1">
                        <div className={`inline-flex items-center gap-1.5 text-sm font-semibold ${ACCENT_TEXT}`}>
                            <IconMCP className="text-base" />
                            Missing capabilities
                        </div>
                        <h3 className="m-0 text-xl font-semibold">No reports in this date range</h3>
                        <p className="m-0 text-sm text-secondary">
                            Agents can report a missing capability when the available tools cannot complete a task. Each
                            report appears here with the most recent first.
                        </p>
                    </div>
                </div>

                {/* Wizard commands only work against cloud; self-hosted gets the manual path promoted instead. */}
                {isCloudOrDev ? (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 text-xs text-tertiary">
                            Run Wizard from your MCP server&apos;s project root. The setup agent enables reporting:
                        </p>
                        <CommandBlock
                            command={command}
                            copyLabel="MCP analytics Wizard command"
                            ariaLabel="Copy MCP analytics Wizard command"
                            size="md"
                            decoration="rainbow"
                            className="bg-bg-light border border-border hover:border-primary"
                        />
                    </div>
                ) : null}

                <p className="m-0 text-xs text-tertiary">
                    {isCloudOrDev ? 'To configure reporting manually, set' : 'Set'} <code>reportMissing: true</code>{' '}
                    when you initialize the PostHog MCP SDK, and agents get a <code>get_more_tools</code> tool they can
                    call when they&apos;re stuck.
                </p>

                <LemonButton
                    type={isCloudOrDev ? 'tertiary' : 'primary'}
                    size={isCloudOrDev ? 'xsmall' : 'small'}
                    icon={<IconBook />}
                    to={MISSING_CAPABILITY_DOCS_URL}
                    targetBlank
                    className="self-start"
                >
                    {isCloudOrDev ? 'Read the setup docs' : 'Set up missing-capability reports'}
                </LemonButton>
            </div>

            <div
                className="hidden min-w-0 flex-col justify-center gap-3 rounded-md border border-primary p-10 md:flex dark:[--empty-state-accent:var(--empty-state-accent-dark)]"
                style={{
                    backgroundImage:
                        'linear-gradient(135deg, color-mix(in oklab, var(--empty-state-accent) 16%, transparent) 0%, color-mix(in oklab, var(--empty-state-accent) 5%, transparent) 45%, transparent 80%)',
                }}
            >
                <div className="flex items-center gap-2 text-xs font-semibold text-secondary">
                    <span
                        className="size-2 animate-pulse rounded-full bg-[var(--empty-state-accent)] motion-reduce:animate-none dark:bg-[var(--empty-state-accent-dark)]"
                        aria-hidden="true"
                    />
                    Example reports
                </div>
                <MissingCapabilitiesPreview />
            </div>
        </div>
    )
}

function NoSearchResultsState({ search }: { search: string }): JSX.Element {
    return (
        <div className="p-6 text-center text-sm text-secondary">
            No reports match “{search}”. Try a broader term or a wider date range.
        </div>
    )
}

function ClientCell({ harness }: { harness: string }): JSX.Element {
    if (isUnidentifiedClient(harness)) {
        return (
            <span className="text-muted" title="This report didn't include which MCP client filed it.">
                Unknown client
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1.5">
            <HarnessLogo category={harness} className="h-3.5 w-3.5" />
            <span className="truncate">{harness}</span>
        </span>
    )
}

export function MCPAnalyticsMissingCapabilities(): JSX.Element {
    const { reports, reportsError, reportsLoading, hasNext, search } = useValues(mcpMissingCapabilitiesLogic)
    const { loadReports, loadMoreReports } = useActions(mcpMissingCapabilitiesLogic)

    const initialLoadFailed = Boolean(reportsError) && reports.length === 0
    const noReports = !reportsLoading && !reportsError && reports.length === 0 && !search

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-missing-capabilities">
            <FilterBar />
            {reportsError ? (
                <LemonBanner type="error">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>Couldn&apos;t load missing-capability reports. Try again.</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={reportsLoading}
                            onClick={() => (reports.length > 0 ? loadMoreReports() : loadReports())}
                            data-attr="mcp-missing-capabilities-retry"
                        >
                            Try again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : null}
            {initialLoadFailed ? null : noReports ? (
                <NoReportsState />
            ) : (
                <LemonTable<MCPMissingCapabilitiesItem>
                    dataSource={reports}
                    loading={reportsLoading && reports.length === 0}
                    rowKey={(row, index) => `${row.timestamp}-${index}`}
                    emptyState={<NoSearchResultsState search={search} />}
                    columns={[
                        {
                            title: 'When',
                            key: 'timestamp',
                            width: 130,
                            render: (_, row) => <TZLabel time={row.timestamp} />,
                        },
                        {
                            title: 'The ask',
                            key: 'intent',
                            render: (_, row) =>
                                row.intent ? (
                                    <span className="text-base">{row.intent}</span>
                                ) : (
                                    // The agent called get_more_tools without saying what it wanted.
                                    <span className="text-muted text-base">No description given</span>
                                ),
                        },
                        {
                            title: 'Client',
                            key: 'harness',
                            width: 170,
                            render: (_, row) => <ClientCell harness={row.harness} />,
                        },
                        {
                            title: 'Person',
                            key: 'person',
                            width: 200,
                            render: (_, row) => (
                                <PersonDisplay
                                    person={{
                                        distinct_id: row.distinct_id,
                                        properties: parsePersonProperties(row.person_properties),
                                    }}
                                    withIcon
                                    noPopover={false}
                                />
                            ),
                        },
                    ]}
                />
            )}
            {hasNext ? (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={reportsLoading}
                        onClick={() => loadMoreReports()}
                        data-attr="mcp-missing-capabilities-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

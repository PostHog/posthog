import { useActions, useValues } from 'kea'

import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import { IconLightBulb, IconPlug } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import type { ProductEmptyStateConfig } from 'lib/components/ProductEmptyState/types'
import { TZLabel } from 'lib/components/TZLabel'
import { Toggle, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { MCPMissingCapabilitiesItem, ProductKey } from '~/queries/schema/schema-general'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { labMark, modelLab } from '../aiLabs'
import { McpDateFilter } from '../components/McpDateFilter'
import { MCP_FILTER_ACTIVE_CLASS, McpFacetSelect } from '../components/McpFacetSelect'
import { McpFacetControl, McpSharedFilters } from '../components/McpSharedFilters'
import { HarnessLogo } from '../dashboard/harness'
import { isUnidentifiedClient } from '../dashboard/harnessRegistry'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import {
    DEFAULT_DATE_FILTER,
    REPORT_OUTCOMES,
    ReportOutcome,
    mcpMissingCapabilitiesLogic,
    parsePersonProperties,
} from './mcpMissingCapabilitiesLogic'
import { MissingCapabilitiesPreview } from './MissingCapabilitiesPreview'
import { MissingCapabilitySessionDrawer } from './MissingCapabilitySessionDrawer'

const MISSING_CAPABILITY_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/missing-capability'

const HedgehogPuzzle = pngHoggie(puzzlePng)

// Reports carry the client and, from send_feedback, the model, but no tool, error or duration.
const REPORT_FACET_CONTROLS: readonly McpFacetControl[] = ['harness', 'model']

function FilterBar(): JSX.Element {
    const { search, dateFilter, reportsLoading, outcomes, hasSuggestedFix } = useValues(mcpMissingCapabilitiesLogic)
    const { setSearch, setDateFilter, loadReports, setOutcomes, setHasSuggestedFix } =
        useActions(mcpMissingCapabilitiesLogic)

    return (
        <McpSharedFilters
            pageKey="mcp-missing-capabilities"
            dataAttrPrefix="mcp-missing-capabilities"
            facetControls={REPORT_FACET_CONTROLS}
            pageFacets={
                <>
                    <McpFacetSelect
                        label="Outcome"
                        options={OUTCOME_OPTIONS}
                        value={outcomes.map((outcome) => REPORT_OUTCOMES[outcome])}
                        onChange={(labels) =>
                            setOutcomes(OUTCOME_KEYS.filter((key) => labels.includes(REPORT_OUTCOMES[key])))
                        }
                        dataAttr="mcp-missing-capabilities-filter-outcome"
                    />
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Toggle
                                    variant="outline"
                                    pressed={hasSuggestedFix}
                                    onPressedChange={setHasSuggestedFix}
                                    className={cn(hasSuggestedFix && MCP_FILTER_ACTIVE_CLASS)}
                                    data-attr="mcp-missing-capabilities-filter-suggested-fix"
                                />
                            }
                        >
                            <IconLightBulb />
                            Suggested fix
                        </TooltipTrigger>
                        <TooltipContent>Reports where the agent suggested a fix</TooltipContent>
                    </Tooltip>
                </>
            }
            hasPageFilters={outcomes.length > 0 || hasSuggestedFix}
            onClearPageFilters={() => {
                setOutcomes([])
                setHasSuggestedFix(false)
            }}
            onRefresh={loadReports}
            refreshing={reportsLoading}
        >
            <AnalyticsSearchInput
                value={search}
                onChange={setSearch}
                label="Search what agents asked for"
                placeholder="Search what agents asked for"
                dataAttr="mcp-missing-capabilities-search"
                className="max-w-64 min-w-32 flex-[1_1_8rem]"
            />
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={setDateFilter}
                dataAttr="mcp-missing-capabilities-date-filter"
            />
        </McpSharedFilters>
    )
}

// Rendered by hand: the product is set up, and skipping would hide its whole gate.
const NO_REPORTS_EMPTY_STATE: ProductEmptyStateConfig = {
    productKey: ProductKey.MCP_ANALYTICS,
    productName: 'Missing capabilities',
    icon: <IconPlug />,
    accentColor: 'var(--color-product-mcp-analytics-light)',
    accentColorDark: 'var(--color-product-mcp-analytics-dark)',
    hedgehog: HedgehogPuzzle,
    text: {
        'needs-setup': {
            headline: "Hear what your agents couldn't do",
            lead: "Agents can report a missing capability when the available tools can't complete a task. Each report shows what they wanted and, often, the fix that would have helped.",
        },
    },
    wizard: { slug: 'mcp-analytics', pinProjectId: true },
    manualSetupUrl: MISSING_CAPABILITY_DOCS_URL,
    statusIndicator: (
        <span className="text-tertiary">
            Run Wizard from your MCP server&apos;s project root. The setup agent turns on reporting.
        </span>
    ),
    previewLabel: 'Reports, once agents send them',
    Preview: MissingCapabilitiesPreview,
    skippable: false,
}

function NoReportsState(): JSX.Element {
    return (
        <div data-attr="mcp-missing-capabilities-empty">
            {/* preview: stays out of setup-funnel events. */}
            <ProductEmptyState config={NO_REPORTS_EMPTY_STATE} mode="needs-setup" preview />
        </div>
    )
}

function NoMatchesState({ search }: { search: string }): JSX.Element {
    return (
        <div className="p-6 text-center text-sm text-secondary">
            {search
                ? `No reports match “${search}”. Try a broader term or a wider date range.`
                : 'No reports match these filters. Try a wider date range or clear the filters.'}
        </div>
    )
}

const OUTCOME_KEYS = Object.keys(REPORT_OUTCOMES) as ReportOutcome[]
const OUTCOME_OPTIONS = OUTCOME_KEYS.map((key) => ({ value: REPORT_OUTCOMES[key], calls: 0 }))

const OUTCOME_HELP =
    "Whether the agent says it still finished the user's task despite the gap. Blocked: it could not. Completed anyway: it found another way. Not reported: the report did not say, which is always the case for get_more_tools reports."
const SUGGESTED_HELP =
    'The change the agent says would have helped, such as a tool to add, from its send_feedback report.'

function AskCell({ row }: { row: MCPMissingCapabilitiesItem }): JSX.Element {
    return row.intent ? <span>{row.intent}</span> : <span className="text-muted">No description given</span>
}

function ModelCell({ model }: { model: string }): JSX.Element {
    if (!model) {
        return <span className="text-muted">—</span>
    }
    return (
        <span className="flex max-w-28 items-center gap-1.5">
            <BrandMark name={labMark(modelLab(model))} />
            <span className="truncate" title={model}>
                {model}
            </span>
        </span>
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
        <span className="flex max-w-28 items-center gap-1.5">
            <HarnessLogo category={harness} className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate" title={harness}>
                {harness}
            </span>
        </span>
    )
}

export function MCPAnalyticsMissingCapabilities(): JSX.Element {
    const {
        reports,
        reportsError,
        reportsLoading,
        hasNext,
        search,
        openedReport,
        dateFilter,
        outcomes,
        hasSuggestedFix,
    } = useValues(mcpMissingCapabilitiesLogic)
    const { loadReports, loadMoreReports, openReport } = useActions(mcpMissingCapabilitiesLogic)
    const { propertyFilters, hasActiveFacetFilters } = useValues(mcpAnalyticsFiltersLogic)

    const initialLoadFailed = Boolean(reportsError) && reports.length === 0
    // Under a filter, empty means no matches, so keep the filter bar.
    const filtered =
        !!search ||
        propertyFilters.length > 0 ||
        hasActiveFacetFilters ||
        outcomes.length > 0 ||
        hasSuggestedFix ||
        dateFilter.dateFrom !== DEFAULT_DATE_FILTER.dateFrom ||
        dateFilter.dateTo !== DEFAULT_DATE_FILTER.dateTo
    const noReports = !reportsLoading && !reportsError && reports.length === 0 && !filtered

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-missing-capabilities">
            {noReports ? null : <FilterBar />}
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
                    emptyState={<NoMatchesState search={search} />}
                    onRow={(row) => ({
                        onClick: () => openReport(row),
                        className: 'cursor-pointer',
                        'data-attr': 'mcp-missing-capabilities-row',
                    })}
                    rowStatus={(row) => (row === openedReport ? 'highlighted' : null)}
                    columns={[
                        {
                            title: 'The ask',
                            key: 'intent',
                            className: 'min-w-48',
                            render: (_, row) => <AskCell row={row} />,
                        },
                        {
                            title: 'Suggested fix',
                            key: 'suggested_improvement',
                            className: 'min-w-44',
                            tooltip: SUGGESTED_HELP,
                            render: (_, row) =>
                                row.suggested_improvement ? (
                                    <span className="text-secondary">{row.suggested_improvement}</span>
                                ) : (
                                    <span className="text-muted">—</span>
                                ),
                        },
                        {
                            title: 'Outcome',
                            key: 'outcome',
                            width: 110,
                            tooltip: OUTCOME_HELP,
                            render: (_, row) =>
                                row.outcome === 'blocked' ? (
                                    <LemonTag type="danger" size="small">
                                        {REPORT_OUTCOMES.blocked}
                                    </LemonTag>
                                ) : row.outcome === 'completed' ? (
                                    <LemonTag type="muted" size="small">
                                        {REPORT_OUTCOMES.completed}
                                    </LemonTag>
                                ) : (
                                    <span className="text-muted">{REPORT_OUTCOMES.not_reported}</span>
                                ),
                        },
                        {
                            title: 'Harness',
                            key: 'harness',
                            width: 120,
                            render: (_, row) => <ClientCell harness={row.harness} />,
                        },
                        {
                            title: 'Model',
                            key: 'model',
                            width: 110,
                            render: (_, row) => <ModelCell model={row.model} />,
                        },
                        {
                            title: 'Person',
                            key: 'person',
                            width: 200,
                            render: (_, row) => (
                                // The person popover takes the click, so it does not also open the session.
                                <span className="block max-w-32 truncate" onClick={(event) => event.stopPropagation()}>
                                    <PersonDisplay
                                        person={{
                                            distinct_id: row.distinct_id,
                                            properties: parsePersonProperties(row.person_properties),
                                        }}
                                        withIcon
                                        noPopover={false}
                                    />
                                </span>
                            ),
                        },
                        {
                            title: 'When',
                            key: 'timestamp',
                            width: 90,
                            align: 'right',
                            render: (_, row) => <TZLabel time={row.timestamp} />,
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
            <MissingCapabilitySessionDrawer reports={reports} openedReport={openedReport} onOpen={openReport} />
        </div>
    )
}

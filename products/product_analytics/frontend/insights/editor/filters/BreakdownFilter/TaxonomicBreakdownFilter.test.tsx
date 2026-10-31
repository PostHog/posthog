import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DataWarehouseNode, FunnelsDataWarehouseNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { buildFunnelsQuery, buildTrendsQuery, MockResponse, renderInsightPage } from '~/test/insight-testing'

// The disabled-reason copy shows through LemonButton's Tooltip, which has a 400ms open
// delay. On contended CI shards that delay plus jsdom positioning can exceed the default
// 1s waitFor budget, so the hover assertions flake. Give them room (and raise the per-test
// timeout to match, so a single waitFor can't exhaust the 5s default test budget).
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

// Monaco does not render under jsdom, and the SQL expression tab mounts it eagerly. The stand-in
// exposes `sourceQuery`, which is the only place the editor's validation scope is observable.
jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({ sourceQuery }: { sourceQuery?: { query?: string } }): JSX.Element => (
        <textarea
            aria-label="SQL expression"
            data-attr="sql-expression-editor"
            data-source-query={sourceQuery?.query ?? ''}
        />
    ),
}))

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

async function waitForBreakdownButton(): Promise<HTMLElement> {
    return waitFor(() => {
        const button = screen.getByTestId('add-breakdown-button')
        expect(button).toBeInTheDocument()
        return button
    })
}

// The picker lists its categories inside a dropdown, so an offered category is only in the DOM
// once that dropdown is open. The rail toggle sits below the category list and does not depend on
// which categories are offered, so waiting for it proves the menu rendered. That is what makes a
// later "this category is absent" assertion mean something.
async function openCategoryDropdown(): Promise<void> {
    await userEvent.click(await screen.findByTestId('taxonomic-category-dropdown-trigger-pill'))
    await screen.findByTestId('taxonomic-category-rail-toggle')
}

describe('TaxonomicBreakdownFilter', () => {
    afterEach(cleanup)

    describe('not at cap', () => {
        it('renders the + Breakdown button as enabled when no breakdowns are set', async () => {
            renderInsightPage({ query: buildTrendsQuery() })
            const button = await waitForBreakdownButton()
            expect(button).toHaveAttribute('aria-disabled', 'false')
        })
    })

    describe('at the trends 3-breakdown cap', () => {
        const queryAtCap = buildTrendsQuery({
            breakdownFilter: {
                breakdowns: [
                    { property: '$browser', type: 'event' },
                    { property: '$os', type: 'event' },
                    { property: '$device_type', type: 'event' },
                ],
            },
        })

        it('keeps the + Breakdown button rendered but disabled', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            expect(button).toBeInTheDocument()
            expect(button).toHaveAttribute('aria-disabled', 'true')
        })

        it('surfaces the trends cap explanation on hover', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                expect(screen.getByText(/up to 3 properties/i)).toBeInTheDocument()
            })
        })

        it('embeds the docs link inline in the tooltip', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                const docsLink = screen.getByText(/read the docs/i).closest('a')
                expect(docsLink).not.toBeNull()
                expect(docsLink).toHaveAttribute('href', 'https://posthog.com/docs/product-analytics/trends/breakdowns')
            })
        })

        it('offers the SQL editor escape hatch when the insight is SQL-convertible', async () => {
            renderInsightPage({
                query: queryAtCap,
                mocks: {
                    mockResponses: [
                        {
                            match: (query) => query.kind === NodeKind.TrendsQuery,
                            response: { results: [], hogql: 'SELECT count() FROM events' } as any,
                        },
                    ],
                },
            })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                const sqlLink = screen.getByTestId('breakdown-limit-edit-sql')
                expect(sqlLink).toBeInTheDocument()
                expect(sqlLink.getAttribute('href')).toMatch(/\/sql/)
            })
        })
    })

    describe('on a data warehouse series', () => {
        const warehouseSeries: DataWarehouseNode = {
            kind: NodeKind.DataWarehouseNode,
            id: 'ad_stats',
            name: 'ad_stats',
            table_name: 'ad_stats',
            id_field: 'id',
            timestamp_field: 'reported_at',
            distinct_id_field: 'account_id',
        }

        const warehouseQuery: TrendsQuery = buildTrendsQuery({ series: [warehouseSeries] })

        const warehouseSchema = {
            tables: {
                ad_stats: {
                    name: 'ad_stats',
                    type: 'data_warehouse',
                    id: 'ad_stats',
                    fields: {
                        campaign_id: { name: 'campaign_id', hogql_value: 'campaign_id', type: 'string' },
                        campaign: {
                            name: 'campaign',
                            hogql_value: 'campaign',
                            type: 'lazy_table',
                            table: 'campaigns',
                        },
                    },
                },
                campaigns: {
                    name: 'campaigns',
                    type: 'data_warehouse',
                    id: 'campaigns',
                    fields: {
                        campaign_name: { name: 'campaign_name', hogql_value: 'campaign_name', type: 'string' },
                    },
                },
            },
        }

        const schemaMocks: MockResponse[] = [
            {
                match: (query) => query.kind === NodeKind.DatabaseSchemaQuery,
                response: warehouseSchema as any,
            },
        ]

        const warehouseStep: FunnelsDataWarehouseNode = {
            kind: NodeKind.FunnelsDataWarehouseNode,
            id: 'ad_stats',
            name: 'ad_stats',
            table_name: 'ad_stats',
            id_field: 'id',
            timestamp_field: 'reported_at',
            aggregation_target_field: 'account_id',
        }

        it('offers a joined table column, and scopes its SQL expressions to the series table', async () => {
            renderInsightPage({
                query: warehouseQuery,
                mocks: { additionalMockResponses: schemaMocks },
            })
            await userEvent.click(await waitForBreakdownButton())

            await waitFor(() => {
                expect(screen.getAllByText('campaign.campaign_name').length).toBeGreaterThan(0)
            })

            await openCategoryDropdown()
            await userEvent.click(
                await screen.findByTestId(
                    `taxonomic-category-dropdown-item-${TaxonomicFilterGroupType.HogQLExpression}`
                )
            )

            // The editor defaults to the events table, which marks every warehouse column unknown
            // without telling the user why.
            const editors = await screen.findAllByTestId('sql-expression-editor')
            expect(new Set(editors.map((editor) => editor.getAttribute('data-source-query')))).toEqual(
                new Set(['SELECT * FROM ad_stats'])
            )
        })

        it('withholds the SQL expression escape hatch when an events series is mixed in', async () => {
            renderInsightPage({
                query: buildTrendsQuery({
                    series: [warehouseSeries, { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
                }),
                mocks: { additionalMockResponses: schemaMocks },
            })
            await userEvent.click(await waitForBreakdownButton())

            await openCategoryDropdown()
            expect(
                screen.queryByTestId(`taxonomic-category-dropdown-item-${TaxonomicFilterGroupType.HogQLExpression}`)
            ).not.toBeInTheDocument()
        })

        it('offers a warehouse funnel only its own columns, without joined paths or SQL expressions', async () => {
            renderInsightPage({
                query: buildFunnelsQuery({ series: [warehouseStep, warehouseStep] }),
                mocks: { additionalMockResponses: schemaMocks },
            })
            await userEvent.click(await waitForBreakdownButton())

            await waitFor(() => {
                expect(screen.getAllByText('campaign_id').length).toBeGreaterThan(0)
            })
            expect(screen.queryByText('campaign.campaign_name')).not.toBeInTheDocument()

            await openCategoryDropdown()
            expect(
                screen.getByTestId(
                    `taxonomic-category-dropdown-item-${TaxonomicFilterGroupType.DataWarehouseProperties}`
                )
            ).toBeInTheDocument()
            expect(
                screen.queryByTestId(`taxonomic-category-dropdown-item-${TaxonomicFilterGroupType.HogQLExpression}`)
            ).not.toBeInTheDocument()
        })
    })

    describe('at the funnel cohort cap', () => {
        it('surfaces the funnel cohort explanation and the cohort-anchored docs link', async () => {
            renderInsightPage({
                query: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    ],
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1],
                    },
                } as any,
            })
            const button = await waitForBreakdownButton()
            expect(button).toHaveAttribute('aria-disabled', 'true')
            await userEvent.hover(button)
            await waitFor(() => {
                expect(screen.getByText(/single cohort breakdown/i)).toBeInTheDocument()
                const docsLink = screen.getByText(/read the docs/i).closest('a')
                expect(docsLink).not.toBeNull()
                expect(docsLink).toHaveAttribute(
                    'href',
                    'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
                )
            })
        })
    })
})

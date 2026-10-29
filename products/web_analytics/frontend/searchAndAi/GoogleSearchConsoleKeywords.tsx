import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps, PathCleaningFilter } from '~/types'

import { SearchAndAiLoading } from './SearchAndAiLoading'
import {
    GOOGLE_SEARCH_CONSOLE_DOCS_URL,
    PagePerformanceWindow,
    buildGoogleSearchConsoleQuery,
    findGoogleSearchConsoleTable,
} from './searchAndAiQueries'
import { SearchAndAiQuery } from './SearchAndAiQuery'

const SearchHog = pngHoggie(magnifyingGlassPng)

export interface GoogleSearchConsoleKeywordsProps {
    page: string
    window: PagePerformanceWindow
    isPathCleaningEnabled: boolean
    pathCleaningFilters: PathCleaningFilter[] | undefined
    insightProps: InsightLogicProps
    uniqueKey: string
    connectPrompt?: 'illustration' | 'text'
    onConnectClick?: () => void
}

export function GoogleSearchConsoleKeywords({
    page,
    window,
    isPathCleaningEnabled,
    pathCleaningFilters,
    insightProps,
    uniqueKey,
    connectPrompt = 'illustration',
    onConnectClick,
}: GoogleSearchConsoleKeywordsProps): JSX.Element {
    const { dataWarehouseTables, database, databaseLoading, databaseLoadError } = useValues(databaseTableListLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)

    useOnMountEffect(() => {
        if (!database) {
            loadDatabase()
        }
    })

    const gscTableName = findGoogleSearchConsoleTable(dataWarehouseTables)
    const query = useMemo(
        (): DataTableNode | null =>
            gscTableName
                ? {
                      kind: NodeKind.DataTableNode,
                      source: {
                          kind: NodeKind.HogQLQuery,
                          query: buildGoogleSearchConsoleQuery(
                              gscTableName,
                              page,
                              window,
                              isPathCleaningEnabled,
                              pathCleaningFilters
                          ),
                          tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                      },
                      embedded: true,
                      showActions: false,
                  }
                : null,
        [gscTableName, page, window, isPathCleaningEnabled, pathCleaningFilters]
    )

    if (!query) {
        if (databaseLoadError && !databaseLoading) {
            return (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadDatabase({ force: true }),
                        loading: databaseLoading,
                    }}
                >
                    Could not load data warehouse tables. Try again to check for your Google Search Console source.
                </LemonBanner>
            )
        }
        if (databaseLoading || !database) {
            return <SearchAndAiLoading loading label="Checking Google Search Console" className="min-h-64" />
        }
        if (connectPrompt === 'text') {
            return (
                <div className="flex flex-col items-center gap-3 py-8 text-center">
                    <p className="text-secondary max-w-md m-0">
                        Google Search Console shows the search queries and average positions each page ranks for.
                        Connect it as a data warehouse source to unlock this breakdown.
                    </p>
                    <LemonButton
                        type="primary"
                        to={GOOGLE_SEARCH_CONSOLE_DOCS_URL}
                        targetBlank
                        sideIcon={<IconOpenInNew />}
                    >
                        Connect Google Search Console
                    </LemonButton>
                </div>
            )
        }
        return (
            <div
                className="flex flex-col items-center gap-4 px-6 py-8 text-center @container"
                data-attr="gsc-connect-empty-state"
            >
                <SearchHog title="" className="w-28" />
                <div className="flex flex-col gap-1 max-w-md">
                    <h3 className="m-0 text-base font-semibold">See what people search to find this page</h3>
                    <p className="m-0 text-secondary">
                        Connect Google Search Console as a data warehouse source to see the queries this page ranks for,
                        its clicks and its average position.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    to={GOOGLE_SEARCH_CONSOLE_DOCS_URL}
                    targetBlank
                    sideIcon={<IconOpenInNew />}
                    onClick={onConnectClick}
                    data-attr="page-report-gsc-connect"
                >
                    Connect Google Search Console
                </LemonButton>
            </div>
        )
    }

    return <SearchAndAiQuery uniqueKey={uniqueKey} query={query} insightProps={insightProps} />
}

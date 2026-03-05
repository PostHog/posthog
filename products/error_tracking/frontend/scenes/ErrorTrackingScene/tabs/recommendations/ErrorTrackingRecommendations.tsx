import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'

import { recommendationsLogic } from './recommendationsLogic'
import { AlertsSetupTile, MissingAlert } from './tiles/AlertsSetupTile'
import { AutocaptureTile } from './tiles/AutocaptureTile'
import { CrossProductTile, MissingProduct } from './tiles/CrossProductTile'
import { ExceptionIngestionTile } from './tiles/ExceptionIngestionTile'
import { LongExistentIssuesTile, LongExistentIssue } from './tiles/LongExistentIssuesTile'
import { SourceControlTile } from './tiles/SourceControlTile'
import { SourceMapsTile } from './tiles/SourceMapsTile'

// ——— Mock data ———

const MOCK_INGESTION_DATA = {
    failedLast7Days: 247,
    failedLast24Hours: 38,
    detectedLibraries: [
        { name: 'posthog-python', docUrl: 'https://posthog.com/docs/libraries/python' },
        { name: 'posthog-node', docUrl: 'https://posthog.com/docs/libraries/node' },
        { name: 'posthog-js', docUrl: 'https://posthog.com/docs/libraries/js' },
    ],
}

const MOCK_LONG_ISSUES: LongExistentIssue[] = [
    {
        id: '1',
        name: 'TypeError: Cannot read property "length" of undefined',
        occurrencesLast7Days: 1247,
        firstSeenDaysAgo: 142,
    },
    { id: '2', name: 'RangeError: Maximum call stack size exceeded', occurrencesLast7Days: 893, firstSeenDaysAgo: 87 },
    { id: '3', name: 'NetworkError: Failed to fetch /api/v1/events', occurrencesLast7Days: 456, firstSeenDaysAgo: 203 },
    {
        id: '4',
        name: 'SyntaxError: Unexpected token < in JSON at position 0',
        occurrencesLast7Days: 234,
        firstSeenDaysAgo: 65,
    },
    { id: '5', name: 'Error: ECONNREFUSED 127.0.0.1:5432', occurrencesLast7Days: 178, firstSeenDaysAgo: 312 },
    { id: '6', name: 'UnhandledPromiseRejection: Request timeout', occurrencesLast7Days: 89, firstSeenDaysAgo: 45 },
]

const MOCK_MISSING_ALERTS: MissingAlert[] = [
    {
        type: 'issue_created',
        label: 'New issue created',
        description: 'Get notified when a brand new error type appears',
    },
    {
        type: 'issue_reopened',
        label: 'Issue reopened',
        description: 'Get notified when a previously resolved issue reoccurs',
    },
    {
        type: 'issue_spiking',
        label: 'Issue spiking',
        description: 'Get notified when an existing issue suddenly increases in volume',
    },
]

const MOCK_PRODUCTS: MissingProduct[] = [
    {
        key: 'session_replay',
        name: 'Session replay',
        enabled: false,
        explanation:
            'Session replay lets you watch exactly what the user did before and after an error occurred. See the full context: clicks, scrolls, page navigations, and console logs — all synchronized with the error timeline.',
    },
    {
        key: 'logs',
        name: 'Log capture',
        enabled: false,
        explanation:
            "Logs provide server-side context that stack traces alone can't give you. Correlate application logs with errors to understand the full chain of events leading to a failure.",
    },
]

const MOCK_SOURCE_MAPS = {
    unresolvedFrames: 1834,
    totalFrames: 2410,
    affectedIssues: 47,
}

const ALL_TILE_IDS = [
    'exception-ingestion',
    'autocapture-off',
    'source-maps',
    'long-existent-issues',
    'alerts-setup',
    'cross-product',
    'source-control',
]

export function ErrorTrackingRecommendations(): JSX.Element {
    const { visibleTileIds } = useValues(recommendationsLogic)

    const tiles = ALL_TILE_IDS.filter((id) => visibleTileIds(id))
    const hasVisibleTiles = tiles.length > 0

    if (!hasVisibleTiles) {
        return <AllClearState />
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-sm text-secondary mb-0">
                        {tiles.length} recommendation{tiles.length !== 1 ? 's' : ''} to improve your error tracking
                        setup
                    </p>
                </div>
            </div>

            <div className="columns-1 md:columns-2 xl:columns-3 gap-3">
                {tiles.includes('exception-ingestion') ? <ExceptionIngestionTile data={MOCK_INGESTION_DATA} /> : null}

                {tiles.includes('autocapture-off') ? <AutocaptureTile onEnable={() => {}} /> : null}

                {tiles.includes('source-maps') ? <SourceMapsTile data={MOCK_SOURCE_MAPS} /> : null}

                {tiles.includes('long-existent-issues') ? <LongExistentIssuesTile issues={MOCK_LONG_ISSUES} /> : null}

                {tiles.includes('alerts-setup') ? <AlertsSetupTile missingAlerts={MOCK_MISSING_ALERTS} /> : null}

                {tiles.includes('cross-product') ? <CrossProductTile products={MOCK_PRODUCTS} /> : null}

                {tiles.includes('source-control') ? <SourceControlTile /> : null}
            </div>
        </div>
    )
}

function AllClearState(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center py-16">
            <div className="rounded-full bg-success-highlight p-4 mb-4">
                <IconCheckCircle className="text-success text-4xl" />
            </div>
            <h3 className="font-semibold text-lg mb-1">All clear!</h3>
            <p className="text-sm text-secondary text-center max-w-sm">
                No recommendations right now. Your error tracking setup looks good. We'll let you know if anything needs
                attention.
            </p>
        </div>
    )
}

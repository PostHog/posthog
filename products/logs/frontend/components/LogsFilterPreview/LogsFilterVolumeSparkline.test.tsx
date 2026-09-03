import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { LogsFilterVolumeSparkline } from './LogsFilterVolumeSparkline'

const EMPTY_GROUP: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [] }
const NON_EMPTY_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: 'api' } as never],
}

describe('LogsFilterVolumeSparkline', () => {
    let sparklineCalls: number
    let cleanupJsdom: () => void
    let cleanupRaf: () => void

    beforeEach(() => {
        sparklineCalls = 0
        cleanupJsdom = setupJsdom()
        cleanupRaf = setupSyncRaf()
        useMocks({
            post: {
                '/api/environments/:team_id/logs/sparkline/': () => {
                    sparklineCalls += 1
                    return [
                        200,
                        [
                            { time: '2026-08-04T11:00:00Z', service: 'api', count: 3, bytes_uncompressed: 2048 },
                            { time: '2026-08-04T11:30:00Z', service: 'api', count: 4, bytes_uncompressed: 4096 },
                        ],
                    ]
                },
            },
        })
        initKeaTests()
    })

    // This suite's jest setup doesn't auto-cleanup, so unmount explicitly or `screen` queries
    // match leftover trees from earlier tests.
    afterEach(() => {
        cleanupRaf()
        cleanupJsdom()
        cleanup()
    })

    it('prompts for a filter and does not query when the group is empty', async () => {
        render(<LogsFilterVolumeSparkline filterGroup={EMPTY_GROUP} metric="bytes" />)

        expect(screen.getByText('Add a filter above to preview matching log volume')).toBeTruthy()
        await waitFor(() => expect(sparklineCalls).toEqual(0))
    })

    it('loads on mount for a pre-filled group and renders the chart with the total', async () => {
        const { container } = render(<LogsFilterVolumeSparkline filterGroup={NON_EMPTY_GROUP} metric="bytes" />)

        await waitFor(() => expect(getHogChart(container).seriesCount).toEqual(1))
        expect(sparklineCalls).toEqual(1)
        expect(screen.getByText('6.1 KB')).toBeTruthy()
    })

    it('formats the header total as a log count for the count metric', async () => {
        render(<LogsFilterVolumeSparkline filterGroup={NON_EMPTY_GROUP} metric="count" />)

        await waitFor(() => expect(screen.getByText('7 logs')).toBeTruthy())
    })

    it('does not refetch when a re-render passes an equal-but-new filter group object', async () => {
        const { rerender } = render(<LogsFilterVolumeSparkline filterGroup={NON_EMPTY_GROUP} metric="bytes" />)
        await waitFor(() => expect(sparklineCalls).toEqual(1))

        rerender(<LogsFilterVolumeSparkline filterGroup={{ ...NON_EMPTY_GROUP }} metric="bytes" />)

        await waitFor(() => expect(screen.getByText('6.1 KB')).toBeTruthy())
        expect(sparklineCalls).toEqual(1)
    })

    it('renders the caption from the loaded points', async () => {
        render(
            <LogsFilterVolumeSparkline
                filterGroup={NON_EMPTY_GROUP}
                metric="bytes"
                renderCaption={({ points, total }) => <div>{`${points?.length} points, ${total} bytes`}</div>}
            />
        )

        await waitFor(() => expect(screen.getByText('2 points, 6144 bytes')).toBeTruthy())
    })
})

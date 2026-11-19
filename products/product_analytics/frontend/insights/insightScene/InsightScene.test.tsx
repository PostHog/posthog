import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { InsightScene } from './InsightScene'

jest.mock('products/product_analytics/frontend/insights/insightScene/InsightAsScene', () => ({
    InsightAsScene: () => <div>Insight editor</div>,
}))
jest.mock('products/posthog_ai/frontend/api/logics', () => ({ useAttachedContext: jest.fn() }))

describe('InsightScene', () => {
    afterEach(cleanup)

    it('replaces the skeleton with not found when a directly opened subscription has no parent insight', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        router.actions.push('/insights/missing1/subscriptions/123')

        render(<InsightScene />)

        expect(screen.getAllByText('Loading…').length).toBeGreaterThan(0)
        expect(await screen.findByText('Insight not found')).toBeInTheDocument()
        expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    it('keeps the editor hidden while an insight opened from a dashboard tile reloads', async () => {
        const query = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
        }
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [{ id: 42, short_id: 'tile42', query }] },
            },
        })
        initKeaTests()
        const tileProps: InsightLogicProps = {
            dashboardItemId: 'tile42' as InsightShortId,
            dashboardId: 6,
            cachedInsight: { id: 42, short_id: 'tile42' as InsightShortId, query },
            doNotLoad: true,
        }
        insightLogic(tileProps).mount()
        insightDataLogic(tileProps).mount()
        router.actions.push(urls.insightEdit('tile42' as InsightShortId, 6))

        render(<InsightScene />)

        expect(screen.getAllByText('Loading…').length).toBeGreaterThan(0)
        expect(screen.queryByText('Insight editor')).not.toBeInTheDocument()
        expect(await screen.findByText('Insight editor')).toBeInTheDocument()
    })
})

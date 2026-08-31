import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { clickAtIndex, ensureJsdom, hoverUntilTooltip } from '@posthog/quill-charts/testing'

import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTopToBottomFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import { groupsModel } from '~/models/groupsModel'
import { dataNodeLogic, type DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelBarHorizontalChart } from './FunnelBarHorizontalChart'

jest.mock('scenes/trends/persons-modal/PersonsModal', () => ({ openPersonsModal: jest.fn() }))
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { openPersonsModal } = require('scenes/trends/persons-modal/PersonsModal')

ensureJsdom()

let uniqueNode = 0

/** Mounts the chart and returns the event wrapper of the first step's bar. */
async function renderFirstStepBar(inCardView: boolean): Promise<HTMLElement> {
    const dashboardItemId = `FunnelBarHorizontalChartTest.${uniqueNode++}` as InsightShortId
    const fixture = funnelTopToBottomFixture as any
    const source = fixture.query.source
    const cachedInsight = { ...fixture, short_id: dashboardItemId }
    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, source),
        doNotLoad: true,
    }

    render(
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <FunnelBarHorizontalChart inCardView={inCardView} />
            </BindLogic>
        </BindLogic>
    )

    await waitFor(() => expect(screen.getAllByLabelText(/chart with/i).length).toBeGreaterThan(0), { timeout: 4000 })
    return screen.getAllByLabelText(/chart with/i)[0].parentElement!
}

describe('FunnelBarHorizontalChart', () => {
    beforeEach(() => {
        initKeaTests()
        groupsModel.mount()
        ;(openPersonsModal as jest.Mock).mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    // A card-view bar used to render the hint while its click handler was withheld, so the tooltip
    // promised a drill-in that never happened on dashboards, notebooks, and PostHog AI answers.
    describe.each([
        ['the insight scene', false],
        ['a card view', true],
    ])('in %s', (_surface, inCardView) => {
        it('opens the persons modal for the bar it invites the user to click', async () => {
            const bar = await renderFirstStepBar(inCardView)

            const tooltip = await hoverUntilTooltip(bar, 0, 1)
            expect(tooltip.textContent).toContain('Click to view')

            await clickAtIndex(bar, 0, 1)
            await waitFor(() => expect(openPersonsModal).toHaveBeenCalled())
            expect((openPersonsModal as jest.Mock).mock.calls[0][0].query).toMatchObject({
                kind: NodeKind.FunnelsActorsQuery,
                funnelStep: 1,
            })
        })
    })
})

import { act, cleanup, render, waitFor } from '@testing-library/react'

import api from 'lib/api'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId, SidePanelTab } from '~/types'

import * as metricsApi from 'products/data_catalog/frontend/generated/api'
import { metricsLogic } from 'products/data_catalog/frontend/metricsLogic'
import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { InsightModals } from './InsightModals'

jest.mock('lib/components/AddToDashboard/AddToDashboardModal', () => ({ AddToDashboardModal: () => null }))
jest.mock('lib/components/Sharing/SharingModal', () => ({ SharingModal: () => null }))
jest.mock('lib/components/TakeScreenshot/ScreenShotEditor', () => ({ ScreenShotEditor: () => null }))
jest.mock('lib/components/TerraformExporter/TerraformExportModal', () => ({ TerraformExportModal: () => null }))
jest.mock('scenes/dashboard/NewDashboardModal', () => ({ NewDashboardModal: () => null }))
jest.mock('products/subscriptions/frontend/components/Subscriptions/SubscriptionsModal', () => ({
    SubscriptionsModal: () => null,
}))

const insightLogicProps: InsightLogicProps = {
    dashboardItemId: 'insight1' as InsightShortId,
    cachedInsight: {
        id: 1,
        short_id: 'insight1' as InsightShortId,
        saved: true,
        query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' } as HogQLQuery,
    },
}

describe('InsightModals sidebar data loading', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(metricsApi, 'dataCatalogMetricsList').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        })
        jest.spyOn(api.endpoint, 'list').mockResolvedValue({ results: [], count: 0, next: null })
        sceneLayoutLogic.mount()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['inline', 'actions'] as const)('loads catalogs only when the %s sidebar opens', async (panel) => {
        render(<InsightModals insightLogicProps={insightLogicProps} />)
        expect(metricsApi.dataCatalogMetricsList).not.toHaveBeenCalled()
        expect(api.endpoint.list).not.toHaveBeenCalled()

        act(() => {
            if (panel === 'inline') {
                sceneLayoutLogic.actions.setScenePanelOpen(true)
            } else {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Info)
            }
        })
        await waitFor(() => {
            expect(metricsApi.dataCatalogMetricsList).toHaveBeenCalledTimes(1)
            expect(api.endpoint.list).toHaveBeenCalledTimes(1)
        })
    })

    it('loads catalogs when navigating with the sidebar already open', async () => {
        sceneLayoutLogic.actions.setScenePanelOpen(true)
        render(<InsightModals insightLogicProps={insightLogicProps} />)
        await waitFor(() => {
            expect(metricsApi.dataCatalogMetricsList).toHaveBeenCalledTimes(1)
            expect(api.endpoint.list).toHaveBeenCalledTimes(1)
        })
    })

    it.each(['metric', 'endpoint'] as const)(
        'loads the %s catalog when its modal opens without the sidebar',
        async (modal) => {
            render(<InsightModals insightLogicProps={insightLogicProps} />)
            act(() => {
                if (modal === 'metric') {
                    metricsLogic.actions.openMetricFromInsightModal()
                } else {
                    endpointLogic.actions.openCreateFromInsightModal()
                }
            })
            await waitFor(() =>
                expect(
                    modal === 'metric' ? metricsApi.dataCatalogMetricsList : api.endpoint.list
                ).toHaveBeenCalledTimes(1)
            )
            expect(modal === 'metric' ? api.endpoint.list : metricsApi.dataCatalogMetricsList).not.toHaveBeenCalled()
        }
    )
})

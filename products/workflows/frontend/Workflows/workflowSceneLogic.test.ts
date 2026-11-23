import { router } from 'kea-router'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { workflowSceneLogic } from './workflowSceneLogic'

describe('workflowSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // Guards the side panel wiring: the access control (and activity) tab only appears when the scene logic
    // — the one sidePanelContextLogic reads SIDE_PANEL_CONTEXT_KEY from — exposes the hog_flow resource.
    it('exposes the hog_flow access control context for a saved workflow', () => {
        const logic = workflowSceneLogic({ id: '0190abcd-1234-7000-8000-000000000000' })
        logic.mount()

        expect(logic.values.sidePanelContext).toEqual({
            activity_scope: ActivityScope.HOG_FLOW,
            activity_item_id: '0190abcd-1234-7000-8000-000000000000',
            access_control_resource: 'hog_flow',
            access_control_resource_id: '0190abcd-1234-7000-8000-000000000000',
        })
        expect(logic.values.breadcrumbs.map((crumb) => crumb.name)).toEqual(['Workflows', 'Manage workflow'])
    })

    it('exposes no access control context for an unsaved workflow', () => {
        const logic = workflowSceneLogic({ id: 'new' })
        logic.mount()

        expect(logic.values.sidePanelContext).toBeNull()
        expect(logic.values.breadcrumbs.map((crumb) => crumb.name)).toEqual(['Workflows', 'New workflow'])
    })

    it.each([
        ['logs', 'invocations'],
        ['suggestions', 'self-driving'],
    ])('sends an old /%s link to the %s tab with its filters', (oldTab, newTab) => {
        workflowSceneLogic({ id: 'wf-1' }).mount()

        router.actions.push(`/workflows/wf-1/${oldTab}`, { search: 'error' })

        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflow('wf-1', newTab)}$`))
        expect(router.values.searchParams).toEqual({ search: 'error' })
    })

    it('opens the tab the url names', () => {
        const logic = workflowSceneLogic({ id: 'wf-1' })
        logic.mount()

        router.actions.push(urls.workflow('wf-1', 'history'))

        expect(logic.values.currentTab).toBe('history')
    })

    it.each([
        ['the step and range a metrics link names', { action: 'email_node', date_from: '-30d' }, 'email_node'],
        ['no step when the link names none', { date_from: '-30d' }, undefined],
    ])('drills the run metrics into %s', (_name, searchParams, instanceId) => {
        workflowSceneLogic({ id: 'wf-1' }).mount()
        const metrics = appMetricsLogic({ logicKey: 'hog-flow-metrics-wf-1' })
        metrics.mount()
        metrics.actions.setParams({ instanceId: 'stale_step' })

        router.actions.push(urls.workflow('wf-1', 'metrics'), searchParams)

        expect(metrics.values.params).toMatchObject({ dateFrom: '-30d' })
        expect(metrics.values.params.instanceId).toBe(instanceId)
    })
})

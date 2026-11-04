import '@testing-library/jest-dom'

import { act, cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { HogFlowListSummaryApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowTemplatesLogic } from './Workflows/templates/workflowTemplatesLogic'
import {
    FIXTURE_METRICS,
    FIXTURE_WORKFLOWS,
    buildWorkflowRow,
    paginated,
} from './Workflows/WorkflowsListV2/workflowsListV2Fixtures'
import { workflowsListV2Logic } from './Workflows/WorkflowsListV2/workflowsListV2Logic'
import { workflowsLogic } from './Workflows/workflowsLogic'
import { WorkflowsScene } from './WorkflowsScene'

const shownRowNames = (): string[] =>
    Array.from(document.querySelectorAll('[data-attr="workflows-list-v2-name"]')).map((el) => el.textContent ?? '')

describe('WorkflowsScene', () => {
    let listRequests: string[]
    let workflows: HogFlowListSummaryApi[]

    beforeEach(() => {
        listRequests = []
        workflows = FIXTURE_WORKFLOWS
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => {
                    listRequests.push(request.url)
                    return [200, paginated(workflows)]
                },
                '/api/projects/:team_id/hog_flows/metrics/global/': ({ request }) => {
                    listRequests.push(request.url)
                    return [200, FIXTURE_METRICS]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.workflows())
    })

    afterEach(() => cleanup())

    it('offers a metrics retry instead of an empty health result when metrics fail', async () => {
        useMocks({
            get: { '/api/projects/:team_id/hog_flows/metrics/global/': () => [500, { detail: 'Unavailable' }] },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'health:failing' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-list-v2-metrics-retry"]')).not.toBeNull()
        )
        expect(document.body).not.toHaveTextContent('No workflows match these filters')
    })

    it('keeps guided automation setup on an empty automation view', async () => {
        workflows = FIXTURE_WORKFLOWS.filter((workflow) => workflow.type === 'messaging')
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'kind:automation' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-automation-empty-state-guided-setup"]')).not.toBeNull()
        )
    })

    it('filters the list and writes pills to the URL', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        const user = userEvent.setup()
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))

        const input = document.querySelector<HTMLInputElement>('input[data-attr="workflows-search"]')
        expect(input).not.toBeNull()
        await user.click(input!)
        await user.keyboard('sta')
        await user.keyboard('{Tab}')
        expect(input).toHaveValue('status:')
        await user.keyboard('{ArrowDown}{Enter}')

        await waitFor(() => expect(shownRowNames()).toEqual(['Welcome series']))
        expect(router.values.searchParams.q).toEqual('status:active')
        expect(input).toHaveValue('')
    })

    it('pages past the first 100 rows, and a new filter starts again on page one', async () => {
        workflows = Array.from({ length: 250 }, (_, i) =>
            buildWorkflowRow({
                id: `wf-${i}`,
                name: `Flow ${String(i).padStart(3, '0')} ${i % 2 ? 'odd' : 'even'}`,
                updated_at: new Date(Date.UTC(2026, 9, 1) - i * 60_000).toISOString(),
            })
        )
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        const user = userEvent.setup()
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 000 even'))

        await user.click(document.querySelector('[aria-label="Next page"]')!)
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 100 even'))
        expect(shownRowNames()).toHaveLength(100)

        // 125 rows match, so a kept page would still show matches 101 and up.
        act(() => workflowsListV2Logic.actions.setValue({ filters: [], text: 'odd' }))
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 001 odd'))
    })

    it.each([
        ['shows Owner when no columns are saved', null, ['Name', 'Status', 'Owner', 'Updated', '', '']],
        [
            'ignores a saved column the list no longer has',
            ['health', 'tags'],
            ['Name', 'Status', 'Health', 'Updated', '', ''],
        ],
        ['shows Kind beside the name', ['type', 'owner'], ['Name', 'Kind', 'Status', 'Owner', 'Updated', '', '']],
    ])('%s', async (_, savedColumns, expectedHeaders) => {
        if (savedColumns) {
            localStorage.setItem(
                'products.workflows.frontend.workflowsListV2Logic.visibleColumns',
                JSON.stringify(savedColumns)
            )
        }
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))
        const headers = Array.from(document.querySelectorAll('[data-attr="workflows-list-v2"] th')).map(
            (th) => th.textContent
        )
        expect(headers).toEqual(expectedHeaders)
    })

    it.each([
        ['the kind facet', true, { q: 'kind:messaging' }],
        ['the old list type tab', false, { type: 'messaging' }],
    ])('opens the template chooser on %s', async (_, listV2, searchParams) => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                hog_flow: AccessControlLevel.Editor,
            },
        }
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: listV2 })
        router.actions.push(urls.workflows(), searchParams)
        const user = userEvent.setup()
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(document.querySelector('[data-attr="new-workflow"]')).not.toBeNull())
        await user.click(document.querySelector('[data-attr="new-workflow"]')!)
        expect(workflowTemplatesLogic.values.typeFilter).toEqual('messaging')
    })

    it('turns an old filter link into pills without loading the old list', async () => {
        const oldListRequests: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/': ({ request }) => {
                    oldListRequests.push(request.url)
                    return [200, paginated([])]
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { type: 'messaging' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(shownRowNames()).toEqual(['Welcome series', 'Renewal reminder', 'Spring promo']))
        expect(router.values.searchParams).toEqual({ q: 'kind:messaging' })
        expect(workflowsLogic.findMounted()).toBeNull()
        // The setup reminder banner asks for one messaging workflow to decide whether it shows.
        const oldListPageRequests = oldListRequests.filter((url) => new URL(url).searchParams.get('limit') !== '1')
        expect(oldListPageRequests).toEqual([])
    })

    it('keeps the old list when the flag is off and never asks for the v2 list', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(document.querySelector('[data-attr="workflows-table"]')).not.toBeNull())
        expect(document.querySelector('input[data-attr="workflows-search"]')).toBeNull()
        await act(async () => {})
        expect(listRequests).toEqual([])
    })
})

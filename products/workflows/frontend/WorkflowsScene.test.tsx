import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
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
                '/api/projects/:team_id/file_system/unfiled/': () => [200, { count: 0 }],
                '/api/projects/:team_id/file_system/': () => [200, paginated([])],
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
        expect(document.body).not.toHaveTextContent('Nothing matches')
    })

    it('keeps the loaded rows when a reload fails', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))

        useMocks({ get: { '/api/projects/:team_id/hog_flows/summaries/': () => [500, { detail: 'Unavailable' }] } })
        act(() => workflowsListV2Logic.actions.loadWorkflows())
        await waitFor(() => expect(workflowsListV2Logic.values.loadFailed).toBe(true))
        expect(shownRowNames()).toContain('Welcome series')
        expect(document.querySelector('[data-attr="workflows-list-v2-retry"]')).toBeNull()
        expect(document.querySelector('[data-attr="workflows-folder-contents"]')).not.toBeNull()
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
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))

        const input = document.querySelector<HTMLInputElement>('input[data-attr="workflows-search"]')
        expect(input).not.toBeNull()
        input!.focus()
        fireEvent.click(input!)
        fireEvent.change(input!, { target: { value: 'sta' } })
        fireEvent.keyDown(input!, { key: 'Tab' })
        expect(input).toHaveValue('status:')
        fireEvent.keyDown(input!, { key: 'ArrowDown' })
        fireEvent.keyDown(input!, { key: 'Enter' })

        await waitFor(() => expect(shownRowNames()).toEqual(['Welcome series']))
        expect(router.values.searchParams.q).toEqual('in:Unfiled status:active')
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
        const scope = [{ facet: 'in', value: 'Unfiled', negated: false }]
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 000 even'))

        fireEvent.click(document.querySelector('[aria-label="Next page"]')!)
        // The folder view spends one row of each page on the ".." row.
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 099 odd'))
        expect(shownRowNames()).toHaveLength(100)

        // 125 rows match, so a kept page would still show matches 101 and up.
        act(() => workflowsListV2Logic.actions.setValue({ filters: scope, text: 'odd' }))
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 001 odd'))
    })

    it('keeps the sort order when a filter changes', async () => {
        workflows = Array.from({ length: 6 }, (_, i) =>
            buildWorkflowRow({ id: `wf-${i}`, name: `Flow ${i} ${i % 2 ? 'odd' : 'even'}` })
        )
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()).toHaveLength(6))

        const nameHeader = Array.from(
            document.querySelectorAll<HTMLElement>('[data-attr="workflows-list-v2"] .LemonTable__header-content')
        ).find((header) => header.textContent === 'Name')!
        fireEvent.click(nameHeader)
        fireEvent.click(nameHeader)
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 5 odd'))

        act(() =>
            workflowsListV2Logic.actions.setValue({
                filters: [{ facet: 'in', value: 'Unfiled', negated: false }],
                text: 'odd',
            })
        )
        await waitFor(() => expect(shownRowNames()).toEqual(['Flow 5 odd', 'Flow 3 odd', 'Flow 1 odd']))
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
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
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

    it('opens the template chooser on the old list type tab', async () => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                hog_flow: AccessControlLevel.Editor,
            },
        }
        featureFlagLogic.actions.setFeatureFlags([], {})
        router.actions.push(urls.workflows(), { type: 'messaging' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(document.querySelector('[data-attr="new-workflow"]')).not.toBeNull())
        fireEvent.click(document.querySelector('[data-attr="new-workflow"]')!)
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

        await waitFor(() => expect(shownRowNames()).toEqual(['Renewal reminder', 'Spring promo', 'Welcome series']))
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

        act(() => router.actions.push(urls.workflows('channels')))
        await waitFor(() => expect(document.querySelector('[data-attr="workflows-table"]')).toBeNull())
        expect(workflowsLogic.findMounted()).not.toBeNull()
    })

    describe('project folders', () => {
        let files: FileSystemEntry[]

        const renderScene = (q: string): void => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
            router.actions.push(urls.workflows(), { q })
            render(
                <Provider>
                    <WorkflowsScene />
                </Provider>
            )
        }

        beforeEach(() => {
            files = [
                { id: 'billing', path: 'Billing', type: 'folder' },
                { id: 'cards', path: 'Billing/Cards', type: 'folder' },
                { id: 'welcome', path: 'Billing/Welcome series', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id },
                {
                    id: 'renewal',
                    path: 'Billing/Cards/Renewal reminder',
                    type: 'hog_flow',
                    ref: FIXTURE_WORKFLOWS[1].id,
                },
            ]
            useMocks({
                get: {
                    '/api/projects/:team_id/file_system/unfiled/': () => [200, { count: 0 }],
                    '/api/projects/:team_id/file_system/': ({ request }) => {
                        const search = new URL(request.url).searchParams.get('search') ?? ''
                        const type = search.replace('type:', '')
                        return [
                            200,
                            paginated(files.filter((file) => (type.startsWith('-') ? false : file.type === type))),
                        ]
                    },
                },
            })
        })

        it('shows workflow descriptions inside a folder as the flat list does', async () => {
            renderScene('in:Billing')
            await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))
            expect(document.querySelector('[data-attr="workflows-list-v2-description"]')).toHaveTextContent(
                'Greets new sign-ups'
            )
        })

        it('shows no workflow as Unfiled until the project folders load', async () => {
            let releaseScan = (): void => {}
            const scanHeld = new Promise<void>((resolve) => (releaseScan = resolve))
            useMocks({
                get: {
                    '/api/projects/:team_id/file_system/unfiled/': async () => {
                        await scanHeld
                        return [200, { count: 0 }]
                    },
                },
            })
            renderScene('in:Unfiled')
            await waitFor(() => expect(workflowsListV2Logic.values.listLoaded).toBe(true))
            expect(shownRowNames()).toEqual([])

            releaseScan()
            await waitFor(() => expect(shownRowNames()).toEqual(['Spring promo', 'Sync accounts to CRM']))
            act(() => router.actions.push(urls.workflows(), { q: 'in:Billing/Cards' }))
            await waitFor(() => expect(shownRowNames()).toEqual(['Renewal reminder']))
        })
    })
})

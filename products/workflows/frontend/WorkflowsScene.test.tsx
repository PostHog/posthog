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

import { workflowFoldersLogic } from './Workflows/WorkflowsListV2/workflowFoldersLogic'
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

const shownHeaders = (): (string | null)[] =>
    Array.from(document.querySelectorAll('[data-attr="workflows-list-v2"] th')).map((th) => th.textContent)

describe('WorkflowsScene', () => {
    let listRequests: string[]
    let answeredSearches: string[]
    let workflows: HogFlowListSummaryApi[]

    // The list shows its local matches at once and greys out until the debounced server search answers.
    const waitForSearch = (text: string): Promise<void> =>
        waitFor(() => {
            expect(answeredSearches).toContain(text)
            expect(document.querySelector('[data-attr="workflows-list-v2"] .LemonTable--loading')).toBeNull()
        })

    beforeEach(() => {
        listRequests = []
        answeredSearches = []
        workflows = FIXTURE_WORKFLOWS
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => {
                    listRequests.push(request.url)
                    const search = new URL(request.url).searchParams.get('search')
                    if (search === null) {
                        return [200, paginated(workflows)]
                    }
                    answeredSearches.push(search)
                    const matches = workflows.filter((workflow) =>
                        `${workflow.name}\n${workflow.description}`.toLowerCase().includes(search.toLowerCase())
                    )
                    return [200, paginated(matches)]
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

    it('waits for metrics while pages load, and keeps the page retry beside a metrics failure', async () => {
        const answerLaterPage: ((status: number, body: unknown) => void)[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.get('offset')
                        ? new Promise((resolve) => answerLaterPage.push((status, body) => resolve([status, body])))
                        : [
                              200,
                              paginated(
                                  FIXTURE_WORKFLOWS,
                                  'http://localhost/api/projects/997/hog_flows/summaries/?offset=100'
                              ),
                          ],
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [500, { detail: 'Unavailable' }],
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'health:failing' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )
        const metricsRetry = (): Element | null =>
            document.querySelector('[data-attr="workflows-list-v2-metrics-retry"]')

        await waitFor(() => expect(answerLaterPage).toHaveLength(1))
        await waitFor(() => expect(document.body).toHaveTextContent('Loading more workflows'))
        expect(document.querySelector('[data-attr="workflows-list-v2"] .LemonTable--loading')).not.toBeNull()
        expect(metricsRetry()).toBeNull()

        act(() => answerLaterPage[0](500, { detail: 'Boom' }))
        await waitFor(() => expect(document.body).toHaveTextContent("Couldn't load all workflows"))
        expect(metricsRetry()).toBeNull()

        act(() => workflowsListV2Logic.actions.refreshWorkflows())
        await waitFor(() => expect(metricsRetry()).not.toBeNull())
        expect(document.body).not.toHaveTextContent("Couldn't load all workflows")
        expect(document.body).not.toHaveTextContent('No workflows match these filters')
        expect(document.body).not.toHaveTextContent('Nothing matches')
        await waitFor(() => expect(answerLaterPage).toHaveLength(2))
        act(() => answerLaterPage[1](500, { detail: 'Boom' }))
        await waitFor(() => expect(document.body).toHaveTextContent("Couldn't load all workflows"))
        expect(metricsRetry()).not.toBeNull()
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

    it('waits for later pages before saying nothing matches, and keeps the loaded rows when one fails', async () => {
        const answerLaterPage: ((status: number, body: unknown) => void)[] = []
        const firstPage = paginated(
            [
                buildWorkflowRow({
                    id: 'wf-live',
                    name: 'Live flow',
                    status: 'active',
                    updated_at: '2026-09-02T00:00:00Z',
                }),
            ],
            'http://localhost/api/projects/997/hog_flows/summaries/?offset=100'
        )
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.get('offset')
                        ? new Promise((resolve) => answerLaterPage.push((status, body) => resolve([status, body])))
                        : [200, firstPage],
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled status:draft' })
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(answerLaterPage).toHaveLength(1))
        await waitFor(() => expect(workflowFoldersLogic.values.browserReady).toBe(true))
        await waitFor(() => expect(document.body).toHaveTextContent('Loading more workflows'))
        expect(document.body).not.toHaveTextContent('Nothing matches')

        act(() => answerLaterPage[0](500, { detail: 'Boom' }))
        act(() =>
            workflowsListV2Logic.actions.setValue({
                filters: [{ facet: 'in', value: 'Unfiled', negated: false }],
                text: '',
            })
        )
        await waitFor(() => expect(document.body).toHaveTextContent("Couldn't load all workflows"))
        expect(shownRowNames()).toEqual(['Live flow'])

        fireEvent.click(document.querySelector('[data-attr="workflows-list-v2-retry"]')!)
        await waitFor(() => expect(answerLaterPage).toHaveLength(2))
        act(() => answerLaterPage[1](200, paginated([buildWorkflowRow({ id: 'wf-draft', name: 'Draft flow' })])))
        await waitFor(() => expect(shownRowNames()).toEqual(['Draft flow', 'Live flow']))
        expect(document.body).not.toHaveTextContent("Couldn't load all workflows")
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

    it('pages past the first 100 rows, and a new filter starts again on page one without redrawing kept rows', async () => {
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
        const nameCell = (name: string): Element | undefined =>
            Array.from(document.querySelectorAll('[data-attr="workflows-list-v2-name"]')).find(
                (el) => el.textContent === name
            )
        const keptCell = nameCell('Flow 101 odd')

        // 125 rows match, so a kept page would still show matches 101 and up.
        act(() => workflowsListV2Logic.actions.setValue({ filters: scope, text: 'odd' }))
        await waitForSearch('odd')
        expect(shownRowNames()[0]).toEqual('Flow 001 odd')
        expect(shownRowNames().every((name) => name.endsWith('odd'))).toBe(true)
        expect(nameCell('Flow 101 odd')).toBe(keptCell)
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
        await waitForSearch('odd')
        expect(shownRowNames()).toEqual(['Flow 5 odd', 'Flow 3 odd', 'Flow 1 odd'])
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
        expect(shownHeaders()).toEqual(expectedHeaders)
    })

    it('keeps the columns picked in List options after the list reopens, until they are reset', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        const openList = async (): Promise<void> => {
            render(
                <Provider>
                    <WorkflowsScene />
                </Provider>
            )
            await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))
        }
        const chooseFromListOptions = async (item: string): Promise<void> => {
            fireEvent.click(document.querySelector('[data-attr="workflows-list-v2-options"]')!)
            await waitFor(() => expect(document.querySelector(`[data-attr="${item}"]`)).not.toBeNull())
            fireEvent.click(document.querySelector(`[data-attr="${item}"]`)!)
        }

        await openList()
        await chooseFromListOptions('workflows-list-v2-column-health')
        await chooseFromListOptions('workflows-list-v2-column-owner')
        await waitFor(() => expect(shownHeaders()).toEqual(['Name', 'Status', 'Health', 'Updated', '', '']))

        cleanup()
        await openList()
        expect(shownHeaders()).toEqual(['Name', 'Status', 'Health', 'Updated', '', ''])

        await chooseFromListOptions('workflows-list-v2-reset-columns')
        await waitFor(() => expect(shownHeaders()).toEqual(['Name', 'Status', 'Owner', 'Updated', '', '']))
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
        expect(document.body).not.toHaveTextContent('Create a workflow')
        fireEvent.click(document.querySelector('[data-attr="new-workflow"]')!)

        await waitFor(() => expect(document.body).toHaveTextContent('Create a workflow'))
        expect(document.querySelector('[data-attr="workflow-template-type-messaging"]')?.closest('li')).toHaveClass(
            'LemonSegmentedButton__option--selected'
        )
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

        it('mounts only the sidebar folders in view, and opens a far folder after scrolling to it', async () => {
            const teams = Array.from({ length: 300 }, (_, index) => `Team-${String(index).padStart(3, '0')}`)
            files = [...files, ...teams.map((path) => ({ id: path, path, type: 'folder' }))]
            renderScene('in:Billing')
            const tree = (): HTMLElement => document.querySelector<HTMLElement>('nav [role="tree"]')!
            const treeItems = (): string[] =>
                Array.from(tree().querySelectorAll('[aria-label^="tree item: "]')).map(
                    (item) => item.getAttribute('aria-label') ?? ''
                )
            await waitFor(() => expect(treeItems()).toContain('tree item: Team-000'))
            expect(treeItems().length).toBeLessThan(60)
            expect(treeItems()).not.toContain('tree item: Team-299')

            const viewport = tree().querySelector<HTMLElement>('.ScrollableShadows__inner')!
            Object.defineProperty(viewport, 'clientHeight', { value: 300, configurable: true })
            Object.defineProperty(viewport, 'scrollTop', { value: 0, writable: true, configurable: true })
            act(() => {
                viewport.scrollTop = 31 * 300
                viewport.dispatchEvent(new Event('scroll'))
            })
            await waitFor(() => expect(treeItems()).toContain('tree item: Team-299'))
            expect(treeItems()).not.toContain('tree item: Team-000')
            fireEvent.click(tree().querySelector('[aria-label="tree item: Team-299"]')!)
            await waitFor(() => expect(router.values.searchParams.q).toEqual('in:Team-299'))
        })

        it('lists a bounded number of folders in the Folders menu, and finds a far folder by typing', async () => {
            const teams = Array.from({ length: 300 }, (_, index) => `Team-${String(index).padStart(3, '0')}`)
            files = [...files, ...teams.map((path) => ({ id: path, path, type: 'folder' }))]
            renderScene('in:Billing')
            await waitFor(() => expect(workflowFoldersLogic.values.folderPaths).toContain('Team-299'))
            const menuItems = (): string[] =>
                Array.from(document.querySelectorAll('[role="menuitem"]')).map((item) => item.textContent ?? '')
            const toolbar = document.querySelector('[data-attr="workflows-folder-toolbar"]')!
            fireEvent.click([...toolbar.querySelectorAll('button')].find((button) => button.textContent === 'Folders')!)

            await waitFor(() => expect(document.body).toHaveTextContent('Type to narrow down 254 more folders'))
            expect(menuItems().length).toBeLessThan(60)
            expect(menuItems()).not.toContain('Team-299(0)')

            fireEvent.change(document.querySelector('input[placeholder="Find a folder"]')!, {
                target: { value: 'Team-299' },
            })
            await waitFor(() => expect(menuItems()).toContain('Team-299(0)'))
            expect(document.body).not.toHaveTextContent('Type to narrow down')
            fireEvent.click(
                [...document.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === 'Team-299(0)')!
            )
            await waitFor(() => expect(router.values.searchParams.q).toEqual('in:Team-299'))
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

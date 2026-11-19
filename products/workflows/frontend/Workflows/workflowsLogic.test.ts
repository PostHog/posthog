import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { createElement } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from './hogflows/types'
import { WorkflowsFilters, workflowsLogic } from './workflowsLogic'

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/': { results: [], count: 0 },
            },
        })
        // The filters persist to localStorage, so a test would otherwise start on the previous one's filters.
        localStorage.clear()
        initKeaTests()
        logic = workflowsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each(['/workflows', '/workflows/workflows'])('fills the filters from the query params on %s', (path) => {
        router.actions.push(
            `${path}?created_by=user-uuid&status=active&trigger_type=event&type=messaging&tags=${encodeURIComponent('["growth","billing"]')}`
        )

        expect(logic.values.filters).toEqual({
            search: '',
            createdBy: 'user-uuid',
            status: 'active',
            type: 'messaging',
            triggerType: 'event',
            tags: ['growth', 'billing'],
            page: 1,
        })
    })

    it('saves a row tag edit with only the tags, and shows the name the server stored', async () => {
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: unknown[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { ...workflow, tags: ['growth'] }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.updateWorkflowTags(workflow, ['Growth']))
            .toFinishAllListeners()
            .toMatchValues({ localWorkflowTags: { 'flow-1': ['growth'] } })

        expect(bodies).toEqual([{ tags: ['Growth'] }])
    })

    it("sends a row's next tag save only after the one before it lands", async () => {
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: string[][] = []
        let markFirstInFlight = (): void => {}
        let releaseFirst = (): void => {}
        const firstInFlight = new Promise<void>((resolve) => (markFirstInFlight = resolve))
        const firstReleased = new Promise<void>((resolve) => (releaseFirst = resolve))
        let started = 0
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    started += 1
                    if (started === 1) {
                        markFirstInFlight()
                        await firstReleased
                    }
                    bodies.push(tags)
                    return [200, { ...workflow, tags }]
                },
            },
        })

        logic.actions.updateWorkflowTags(workflow, ['growth'])
        logic.actions.updateWorkflowTags(workflow, ['growth', 'billing'])
        await firstInFlight
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(bodies).toEqual([['growth'], ['growth', 'billing']])
        expect(logic.values.localWorkflowTags).toEqual({ 'flow-1': ['growth', 'billing'] })
    })

    it('parses a url whose only filter is a tag', () => {
        router.actions.push(`/workflows?tags=${encodeURIComponent('["growth"]')}`)

        expect(logic.values.filters.tags).toEqual(['growth'])
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/workflows?status=active&type=messaging')
        expect(logic.values.filters.status).toEqual('active')

        router.actions.push('/workflows')

        expect(logic.values.filters.status).toEqual('active')
        expect(logic.values.filters.type).toEqual('messaging')
        expect(router.values.searchParams).toMatchObject({ status: 'active', type: 'messaging' })
    })
    describe('list actions', () => {
        const LIST_URL = '/api/projects/:team_id/hog_flows/'
        const DETAIL_URL = '/api/projects/:team_id/hog_flows/:id/'
        const workflow = (status: HogFlow['status']): HogFlow =>
            ({ id: 'flow-1', name: 'Churn win-back', status, tags: [] }) as unknown as HogFlow
        let dialogs: LemonDialogProps[]
        let writes: { method: string; path: string; body?: any }[]
        let listQueries: Record<string, string>[]

        const record =
            (status: number, response: unknown) =>
            async ({ request }: MockResolverInfo): Promise<[number, unknown]> => {
                const path = new URL(request.url).pathname.replace(/^.*\/hog_flows\//, '')
                const body = request.method === 'DELETE' ? undefined : await request.json()
                writes.push(
                    body === undefined ? { method: request.method, path } : { method: request.method, path, body }
                )
                return [status, response]
            }
        const STORED_AT = '2026-05-01T00:00:00.000Z'
        // The server's copy of the workflow, which the enable check reads. Null when it can't be read.
        const useListMocks = (
            status = 200,
            response: unknown = { deleted: 1 },
            stored: HogFlow | null = { ...workflow('draft'), actions: [], updated_at: STORED_AT }
        ): void =>
            useMocks({
                get: {
                    [DETAIL_URL]: () => (stored ? [200, stored] : [500, { detail: 'Server error' }]),
                    [LIST_URL]: ({ request }) => {
                        listQueries.push(Object.fromEntries(new URL(request.url).searchParams))
                        return [
                            200,
                            { results: [workflow('archived'), { ...workflow('archived'), id: 'flow-2' }], count: 2 },
                        ]
                    },
                },
                patch: { [DETAIL_URL]: record(status, response) },
                post: { [LIST_URL]: record(status, response), [`${LIST_URL}bulk_delete/`]: record(status, response) },
                delete: { [DETAIL_URL]: record(status === 200 ? 204 : status, status === 200 ? null : response) },
            })
        const showToasts = (): void => {
            lemonToast.dismiss()
            render(createElement(jest.requireActual('react-toastify').ToastContainer))
        }
        const toastShown = async (message: string): Promise<string | null | undefined> =>
            (await screen.findByText(message)).closest('[data-attr$="-toast"]')?.getAttribute('data-attr')
        const confirm = (title: string): void => {
            const onClick = dialogs.find((d) => d.title === title)?.primaryButton?.onClick
            if (!onClick) {
                throw new Error(`No open dialog titled "${title}"`)
            }
            ;(onClick as () => void)()
        }

        beforeEach(() => {
            dialogs = []
            writes = []
            listQueries = []
            jest.spyOn(LemonDialog, 'open').mockImplementation((props) => {
                dialogs.push(props)
            })
        })

        afterEach(() => {
            cleanup()
            // LemonDialog.open mounts its own root on the body, which cleanup() does not remove.
            document.body.innerHTML = ''
            jest.restoreAllMocks()
        })

        it('deletes a workflow only after its dialog is confirmed, then drops it from the tree and reloads', async () => {
            useListMocks()
            const tree = projectTreeDataLogic()
            tree.mount()
            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => logic.actions.deleteWorkflow(workflow('archived'))).toFinishAllListeners()
            expect(writes).toEqual([])
            expect(dialogs[0].description).toContain('permanently delete "Churn win-back"')

            confirm('Delete workflow?')
            await expectLogic(logic)
                .toDispatchActions(tree, [tree.actionCreators.deleteTypeAndRef('hog_flow/', 'flow-1')])
                .toDispatchActions(['loadWorkflowsSuccess'])

            expect(writes).toEqual([{ method: 'DELETE', path: 'flow-1/' }])
            expect(successToast).toHaveBeenCalledWith('Workflow "Churn win-back" deleted')
            tree.unmount()
        })

        it.each([
            [['flow-1'], 1, '1 archived workflow', '1 workflow deleted'],
            // The toast counts what the server deleted, which can be fewer than the rows picked.
            [['flow-1', 'flow-2'], 1, '2 archived workflows', '1 workflow deleted'],
            [['flow-1', 'flow-2', 'flow-3'], 3, '3 archived workflows', '3 workflows deleted'],
        ])('bulk deletes %j after confirming, clears the selection and reloads', async (ids, deleted, noun, toast) => {
            useListMocks(200, { deleted })
            const tree = projectTreeDataLogic()
            tree.mount()
            const successToast = jest.spyOn(lemonToast, 'success')
            logic.actions.selectAllArchivedWorkflows(ids)

            logic.actions.deleteSelectedWorkflows()
            expect(dialogs[0]).toMatchObject({
                title: `Delete ${noun}?`,
                description: `Are you sure you want to permanently delete ${noun}? This action cannot be undone.`,
            })
            expect(writes).toEqual([])

            confirm(`Delete ${noun}?`)
            await expectLogic(logic)
                .toDispatchActions(
                    tree,
                    ids.map((id) => tree.actionCreators.deleteTypeAndRef('hog_flow/', id))
                )
                .toDispatchActions(['clearArchivedWorkflowSelection'])
                .toMatchValues({ selectedArchivedCount: 0 })
                .toDispatchActions(['loadWorkflowsSuccess'])

            expect(writes).toEqual([{ method: 'POST', path: 'bulk_delete/', body: { ids } }])
            expect(successToast).toHaveBeenCalledWith(toast)
            tree.unmount()
        })

        it('opens no bulk delete dialog when nothing is selected', () => {
            logic.actions.deleteSelectedWorkflows()

            expect(dialogs).toEqual([])
        })

        it.each([
            ['active', ' In-progress workflow invocations will end without completing.'],
            ['draft', ''],
        ] as const)('archives the %s workflow after confirming, then returns to the list', async (status, warning) => {
            useListMocks()
            router.actions.push('/workflows/flow-1/workflow')
            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => logic.actions.archiveWorkflow(workflow(status))).toFinishAllListeners()
            expect(dialogs[0].description).toEqual(`Are you sure you want to archive "Churn win-back"?${warning}`)
            expect(writes).toEqual([])

            confirm('Archive workflow?')
            await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

            expect(writes).toEqual([{ method: 'PATCH', path: 'flow-1/', body: { status: 'archived' } }])
            expect(successToast).toHaveBeenCalledWith('Workflow "Churn win-back" archived')
            expect(router.values.location.pathname).toMatch(/\/workflows$/)
        })

        it.each([
            ['delete', (): void => logic.actions.deleteWorkflow(workflow('archived')), 'Delete workflow?', 'workflow'],
            [
                'bulk delete',
                (): void => logic.actions.deleteSelectedWorkflows(),
                'Delete 1 archived workflow?',
                'workflows',
            ],
            ['archive', (): void => logic.actions.archiveWorkflow(workflow('draft')), 'Archive workflow?', 'workflow'],
            ['restore', (): void => logic.actions.restoreWorkflow(workflow('archived')), null, 'workflow'],
        ])('shows the server error and keeps the list when %s fails', async (verb, run, dialogTitle, noun) => {
            useListMocks(500, { detail: 'Workflow is locked' })
            const errorToast = jest.spyOn(lemonToast, 'error')
            await expectLogic(logic, () => logic.actions.loadWorkflows()).toDispatchActions(['loadWorkflowsSuccess'])
            const loaded = logic.values.workflows
            logic.actions.selectAllArchivedWorkflows(['flow-1'])

            await expectLogic(logic, run).toFinishAllListeners()
            if (dialogTitle) {
                confirm(dialogTitle)
            }
            await waitFor(() =>
                expect(errorToast).toHaveBeenCalledWith(
                    `Failed to ${verb.split(' ').pop()} ${noun}: Workflow is locked`
                )
            )

            await expectLogic(logic).toNotHaveDispatchedActions(['loadWorkflows', 'clearArchivedWorkflowSelection'])
            expect(writes).toHaveLength(1)
            expect(logic.values).toMatchObject({ selectedArchivedCount: 1, workflows: loaded })
        })

        it.each([
            ['restore', 'archived', 'draft'],
            ['toggle', 'active', 'draft'],
            ['toggle', 'draft', 'active'],
        ] as const)('%ss the %s workflow to %s and reloads the list', async (verb, from, to) => {
            useListMocks()
            const successToast = jest.spyOn(lemonToast, 'success')
            const action = verb === 'restore' ? logic.actions.restoreWorkflow : logic.actions.toggleWorkflowStatus

            await expectLogic(logic, () => action(workflow(from))).toDispatchActions(['loadWorkflowsSuccess'])

            expect(dialogs).toEqual([])
            // Enabling sends the stamp it checked, so the server refuses it if the steps changed since.
            const fence =
                verb === 'toggle' && to === 'active' ? { base_updated_at: STORED_AT, sandbox_sender_warned: false } : {}
            expect(writes).toEqual([{ method: 'PATCH', path: 'flow-1/', body: { status: to, ...fence } }])
            if (verb === 'restore') {
                expect(successToast).toHaveBeenCalledWith('Workflow "Churn win-back" restored to draft status')
            }
        })

        const withEmail = (status: HogFlow['status'], stepType: string): HogFlow =>
            ({
                ...workflow(status),
                actions: [{ id: 'email', type: stepType }],
                updated_at: STORED_AT,
            }) as unknown as HogFlow

        const ENABLE_DIALOG = 'Enable on the PostHog test sender?'
        const toggleFromList = async (row: HogFlow): Promise<void> => {
            jest.mocked(LemonDialog.open).mockRestore()
            await expectLogic(logic, () => logic.actions.toggleWorkflowStatus(row)).toFinishAllListeners()
        }

        it.each([
            ['on the test sender after "Enable anyway"', 'email_sandbox', null, userEvent.click],
            [
                'on the test sender once when "Enable anyway" is double-clicked',
                'email_sandbox',
                null,
                userEvent.dblClick,
            ],
            [
                'that the server moved to the test sender after "Enable anyway"',
                'function_email',
                'email_sandbox',
                userEvent.click,
            ],
        ] as const)('enables a draft %s', async (_, rowStep, storedStep, press) => {
            useListMocks(200, { deleted: 1 }, withEmail('draft', storedStep ?? rowStep))
            await toggleFromList(withEmail('draft', rowStep))
            expect(await screen.findByText(ENABLE_DIALOG)).toBeTruthy()
            expect(writes).toEqual([])

            await press(screen.getByText('Enable anyway'))
            await waitFor(() => expect(screen.queryByText(ENABLE_DIALOG)).toBeNull())
            await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess']).toFinishAllListeners()

            expect(writes).toEqual([
                {
                    method: 'PATCH',
                    path: 'flow-1/',
                    body: { status: 'active', base_updated_at: STORED_AT, sandbox_sender_warned: true },
                },
            ])
        })

        it('keeps a draft on the test sender off after "Cancel"', async () => {
            useListMocks(200, { deleted: 1 }, withEmail('draft', 'email_sandbox'))
            await toggleFromList(withEmail('draft', 'email_sandbox'))

            await userEvent.click(await screen.findByText('Cancel'))
            await waitFor(() => expect(screen.queryByText(ENABLE_DIALOG)).toBeNull())
            await expectLogic(logic).toFinishAllListeners()

            expect(writes).toEqual([])
        })

        it.each([
            ['disables a workflow on the test sender', 'active', 'email_sandbox', null, 'draft'],
            ['enables a draft on its own sender', 'draft', 'function_email', null, 'active'],
            [
                'enables a draft the server moved to its own sender',
                'draft',
                'email_sandbox',
                'function_email',
                'active',
            ],
        ] as const)('%s without asking', async (_, from, rowStep, storedStep, to) => {
            useListMocks(200, { deleted: 1 }, withEmail(from, storedStep ?? rowStep))
            await toggleFromList(withEmail(from, rowStep))
            await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess']).toFinishAllListeners()

            expect(screen.queryByText(ENABLE_DIALOG)).toBeNull()
            const fence = to === 'active' ? { base_updated_at: STORED_AT, sandbox_sender_warned: false } : {}
            expect(writes).toEqual([{ method: 'PATCH', path: 'flow-1/', body: { status: to, ...fence } }])
        })

        it.each([
            ['fails', null],
            // A response without steps would read as "no test sender steps" and skip the warning.
            ['has no steps', {} as HogFlow],
        ])("enables nothing when the server's copy %s", async (_, stored) => {
            useListMocks(200, { deleted: 1 }, stored)
            showToasts()
            await toggleFromList(withEmail('draft', 'function_email'))

            expect(
                await toastShown("Couldn't check this workflow's email steps. Refresh the page and try again.")
            ).toBe('error-toast')
            expect(screen.queryByText(ENABLE_DIALOG)).toBeNull()
            expect(writes).toEqual([])
        })

        it('opens one dialog when Enable is chosen again while the check runs', async () => {
            const row = withEmail('draft', 'email_sandbox')
            useListMocks(200, { deleted: 1 }, row)
            let release: () => void = () => {}
            const held = new Promise<void>((resolve) => {
                release = resolve
            })
            let markChecking: () => void = () => {}
            const checking = new Promise<void>((resolve) => {
                markChecking = resolve
            })
            useMocks({
                get: {
                    [DETAIL_URL]: async () => {
                        markChecking()
                        await held
                        return [200, row]
                    },
                },
            })
            jest.mocked(LemonDialog.open).mockRestore()

            logic.actions.toggleWorkflowStatus(row)
            await checking
            logic.actions.toggleWorkflowStatus(row)
            release()
            await expectLogic(logic).toFinishAllListeners()
            // Each dialog renders on its own root, so flush them all before counting.
            await act(async () => {})

            expect(screen.getAllByText(ENABLE_DIALOG)).toHaveLength(1)
        })

        it('keeps a draft off when another tab moves it to the test sender after the check', async () => {
            let stored = withEmail('draft', 'function_email')
            useListMocks()
            useMocks({
                get: {
                    [DETAIL_URL]: () => {
                        const checked = stored
                        // Another tab saves right after this page's check reads the steps.
                        stored = {
                            ...withEmail('draft', 'email_sandbox'),
                            updated_at: '2026-05-01T00:05:00.000Z',
                        } as HogFlow
                        return [200, checked]
                    },
                },
                patch: {
                    // The server's revision check: a write based on an older copy is refused.
                    [DETAIL_URL]: async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        writes.push({ method: 'PATCH', path: 'flow-1/', body })
                        if (body.base_updated_at !== stored.updated_at) {
                            return [409, { detail: 'This workflow was updated elsewhere' }]
                        }
                        stored = { ...stored, status: body.status }
                        return [200, stored]
                    },
                },
            })
            showToasts()
            await toggleFromList(withEmail('draft', 'function_email'))
            await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess']).toFinishAllListeners()

            expect(await toastShown('This workflow was edited somewhere else. Review it, then enable it again.')).toBe(
                'warning-toast'
            )
            expect(writes).toEqual([
                {
                    method: 'PATCH',
                    path: 'flow-1/',
                    body: { status: 'active', base_updated_at: STORED_AT, sandbox_sender_warned: false },
                },
            ])
            expect(stored.status).toBe('draft')
        })

        it('duplicates a workflow as a draft copy and reloads the list', async () => {
            useListMocks()

            const content = { trigger: { type: 'event' }, actions: [{ id: 'exit', type: 'exit' }], tags: ['growth'] }
            const original = { ...workflow('active'), ...content, team_id: 997, created_at: '2026-01-01T00:00:00Z' }

            await expectLogic(logic, () => logic.actions.duplicateWorkflow(original as HogFlow)).toDispatchActions([
                'loadWorkflowsSuccess',
            ])

            expect(writes).toEqual([
                { method: 'POST', path: '', body: { name: 'Churn win-back (copy)', status: 'draft', ...content } },
            ])
        })

        it.each<[Partial<WorkflowsFilters>, Record<string, string>]>([
            [{}, { type: 'messaging,automation,loop', offset: '0' }],
            [
                { type: 'loop', page: 3 },
                { type: 'loop', offset: '60' },
            ],
            [
                { tags: ['growth'], triggerType: 'batch', status: 'archived', search: 'win', createdBy: 'user-uuid' },
                {
                    tags: '["growth"]',
                    trigger: '{"type":"batch"}',
                    status: 'archived',
                    search: 'win',
                    created_by: 'user-uuid',
                },
            ],
        ])('lists workflows for the filters %j', async (filters, query) => {
            useListMocks()

            await expectLogic(logic, () => logic.actions.setFilters(filters)).toDispatchActions([
                'loadWorkflowsSuccess',
            ])

            expect(listQueries).toEqual([
                { type: 'messaging,automation,loop', offset: '0', suggestions_first: 'true', limit: '30', ...query },
            ])
        })

        it('returns to page 1 on any filter change but paging, and moves past-the-end pages to the last page', async () => {
            useMocks({ get: { [LIST_URL]: { results: [], count: 31 } } })

            logic.actions.setFilters({ page: 3 })
            logic.actions.setFilters({ search: 'win' })
            expect(logic.values.filters.page).toBe(1)

            await expectLogic(logic, () => logic.actions.setFilters({ page: 5 })).toDispatchActions([
                'loadWorkflowsSuccess',
                logic.actionCreators.setFilters({ page: 2 }),
            ])

            expect(logic.values.pagination).toEqual({ controlled: true, pageSize: 30, currentPage: 2, entryCount: 31 })
        })

        it('tells the user when the list fails to load', async () => {
            useMocks({ get: { [LIST_URL]: () => [500, { detail: 'Service unavailable' }] } })
            const errorToast = jest.spyOn(lemonToast, 'error')

            await expectLogic(logic, () => logic.actions.loadWorkflows()).toDispatchActions(['loadWorkflowsFailure'])

            expect(errorToast).toHaveBeenCalledWith('Failed to load workflows: Service unavailable')
        })

        it('captures which type tab and tag filter the user picked', () => {
            const capture = jest.spyOn(posthog, 'capture')

            logic.actions.selectTypeTab('loop')
            logic.actions.setTagsFilter(['growth', 'billing'], 'tag_click')

            expect(logic.values.filters).toMatchObject({ type: 'loop', tags: ['growth', 'billing'] })
            expect(capture).toHaveBeenCalledWith('workflows type tab selected', { type: 'loop' })
            expect(capture).toHaveBeenCalledWith('workflows tag filter changed', { tags_count: 2, source: 'tag_click' })
        })

        it('tracks the archived rows picked for bulk delete and forgets them on reload', async () => {
            useListMocks()
            expect(logic.values.allArchivedSelected).toBe(false)
            await expectLogic(logic, () => logic.actions.loadWorkflows()).toDispatchActions(['loadWorkflowsSuccess'])

            logic.actions.toggleArchivedWorkflowSelection('flow-1')
            expect(logic.values).toMatchObject({ selectedArchivedCount: 1, allArchivedSelected: false })
            logic.actions.toggleArchivedWorkflowSelection('flow-2')
            expect(logic.values).toMatchObject({ selectedArchivedCount: 2, allArchivedSelected: true })
            logic.actions.toggleArchivedWorkflowSelection('flow-1')
            expect(logic.values).toMatchObject({ selectedArchivedCount: 1, allArchivedSelected: false })

            await expectLogic(logic, () => logic.actions.loadWorkflows()).toDispatchActions(['loadWorkflowsSuccess'])
            expect(logic.values.selectedArchivedCount).toBe(0)
        })
    })
})

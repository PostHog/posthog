import '@testing-library/jest-dom'

import { DndContext, useDndContext } from '@dnd-kit/core'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { HogFlowListSummaryApi, WorkflowViewUpdateApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowTemplatesLogic } from './Workflows/templates/workflowTemplatesLogic'
import {
    FIXTURE_METRICS,
    FIXTURE_WORKFLOWS,
    buildWorkflowRow,
    paginated,
} from './Workflows/WorkflowsListV2/workflowsListV2Fixtures'
import { workflowsListV2Logic } from './Workflows/WorkflowsListV2/workflowsListV2Logic'
import { workflowsSavedViewsLogic } from './Workflows/WorkflowsListV2/workflowsSavedViewsLogic'
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
                '/api/projects/:team_id/workflow_views/': () => [200, paginated([])],
            },
            post: { '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}] },
        })
        initKeaTests()
        router.actions.push(urls.workflows())
    })

    afterEach(() => cleanup())

    it('distinguishes view filters from additions and explains why a built-in view cannot be updated', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { view: 'drafts', q: 'status:draft trigger:event' })
        const user = userEvent.setup()
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-combined-reset-view"]')).not.toBeNull()
        )
        const update = screen.getByText('Update view').closest('button')!
        expect(update).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('Status: Draft').closest('.inline-flex')).toHaveClass(
            'bg-fill-secondary',
            'text-secondary'
        )
        expect(screen.getByText('Trigger: Event').closest('.inline-flex')).toHaveClass('bg-accent-highlight-secondary')
        await user.hover(update)
        expect(
            await screen.findByText("Built-in views can't be changed. Save as a new view instead.")
        ).toBeInTheDocument()
        await user.click(screen.getByLabelText('Remove view filter Status: Draft'))
        expect(screen.queryByText('Status: Draft')).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflows-combined-view-modified"]')).not.toBeNull()
        await user.click(
            Array.from(document.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent?.startsWith('All'))!
        )
        expect(screen.getByText('Trigger: Event').closest('.inline-flex')).toHaveClass('bg-accent-highlight-secondary')
        expect(screen.queryByText('Status: Draft')).not.toBeInTheDocument()
        await user.click(document.querySelector('[data-attr="workflows-combined-reset-view"]')!)
        expect(screen.queryByText('Trigger: Event')).not.toBeInTheDocument()
    })

    it.each([200, 500])(
        'updates the active saved view and releases its loading state after HTTP %s',
        async (status) => {
            const saved = {
                id: '00000000-0000-4000-8000-000000000009',
                name: 'Event drafts',
                version: 1,
                default_key: null,
                deleted: false,
                created_at: '',
                updated_at: '',
                state: {
                    filters: [{ facet: 'status' as const, value: 'draft', negated: false }],
                    text: '',
                    columns: ['owner'],
                },
            }
            let release: () => void = () => {}
            const pending = new Promise<void>((resolve) => {
                release = resolve
            })
            const writes: unknown[] = []
            useMocks({
                get: { '/api/projects/:team_id/workflow_views/': () => [200, paginated([saved])] },
                post: { '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}] },
                patch: {
                    '/api/projects/:team_id/workflow_views/:id/': async ({ request }) => {
                        const body = (await request.json()) as WorkflowViewUpdateApi
                        writes.push(body)
                        await pending
                        return status === 200 ? [200, { ...saved, ...body, version: 2 }] : [500, {}]
                    },
                },
            })
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT!,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                    hog_flow: AccessControlLevel.Editor,
                },
            }
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
            router.actions.push(urls.workflows(), {
                view: saved.id,
                q: 'status:draft trigger:event',
                columns: 'trigger',
            })
            const user = userEvent.setup()
            render(
                <Provider>
                    <DndContext>
                        <WorkflowsScene />
                    </DndContext>
                </Provider>
            )
            const update = (await screen.findByText('Update view')).closest('button')!
            await user.click(update)
            await waitFor(() => expect(writes).toHaveLength(1))
            expect(update).toHaveAttribute('aria-disabled', 'true')
            expect(update).toHaveClass('LemonButton--loading')
            await user.click(update)
            expect(writes).toHaveLength(1)
            await act(async () => {
                release()
            })
            await waitFor(() => expect(workflowsSavedViewsLogic.values.saving).toBe(false))
            expect(writes).toEqual([
                {
                    version: 1,
                    state: {
                        filters: [
                            { facet: 'status', value: 'draft', negated: false },
                            { facet: 'trigger', value: 'event', negated: false },
                        ],
                        text: '',
                        columns: ['trigger'],
                    },
                },
            ])
            const updated = status === 200
            expect(document.querySelector('[data-attr="workflows-combined-view-modified"]') !== null).toBe(!updated)
            expect(document.querySelector('[data-attr="workflows-combined-reset-view"]') !== null).toBe(!updated)
            expect(
                screen.getByText('Trigger: Event').closest('.inline-flex')!.classList.contains('bg-fill-secondary')
            ).toBe(updated)
            const updateAfterSave = document.querySelector('[data-attr="workflows-combined-update-view"]')
            expect(
                updateAfterSave && {
                    disabled: updateAfterSave.getAttribute('aria-disabled'),
                    loading: updateAfterSave.classList.contains('LemonButton--loading'),
                }
            ).toEqual(updated ? null : { disabled: 'false', loading: false })
        }
    )

    it.each([
        [400, true],
        [201, false],
    ])(
        'keeps the save as dialog open with the typed name only while saving fails, after HTTP %s',
        async (status, keepsOpen) => {
            useMocks({
                get: { '/api/projects/:team_id/workflow_views/': () => [200, paginated([])] },
                post: {
                    '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}],
                    '/api/projects/:team_id/workflow_views/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        return status === 201
                            ? [
                                  201,
                                  {
                                      ...body,
                                      id: '00000000-0000-4000-8000-00000000000a',
                                      version: 1,
                                      default_key: null,
                                  },
                              ]
                            : [400, { detail: 'Name unavailable' }]
                    },
                },
            })
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT!,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                    hog_flow: AccessControlLevel.Editor,
                },
            }
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
            router.actions.push(urls.workflows(), { view: 'drafts', q: 'status:draft trigger:event' })
            const user = userEvent.setup()
            render(
                <Provider>
                    <DndContext>
                        <WorkflowsScene />
                    </DndContext>
                </Provider>
            )
            await waitFor(() =>
                expect(document.querySelector('[data-attr="workflows-combined-save-as-new"]')).not.toBeNull()
            )
            await user.click(document.querySelector('[data-attr="workflows-combined-save-as-new"]')!)
            const name = await screen.findByPlaceholderText('For example: Webinar emails')
            await user.type(name, 'Event drafts{Enter}')

            await waitFor(() => expect(workflowsSavedViewsLogic.values.saving).toBe(false))
            if (keepsOpen) {
                expect(name).toBeInTheDocument()
                expect(name).toHaveValue('Event drafts')
                await user.click(screen.getByText('Cancel'))
            }
            await waitFor(() => expect(name).not.toBeInTheDocument())
        }
    )

    it('offers a metrics retry instead of an empty health result when metrics fail', async () => {
        useMocks({
            get: { '/api/projects/:team_id/hog_flows/metrics/global/': () => [500, { detail: 'Unavailable' }] },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'health:failing' })
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-list-v2-metrics-retry"]')).not.toBeNull()
        )
        expect(document.body).not.toHaveTextContent('No workflows match these filters')
        expect(document.body).not.toHaveTextContent('Nothing matches')
    })

    it('shows no rows until the saved view from a view link applies', async () => {
        let release: () => void = () => {}
        const viewsAnswer = new Promise<void>((resolve) => {
            release = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_views/': async () => {
                    await viewsAnswer
                    return [200, paginated([])]
                },
            },
            post: { '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}] },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { view: 'drafts' })
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() => expect(workflowsListV2Logic.values.listLoaded).toBe(true))
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-list-v2-views-loading"]')).not.toBeNull()
        )
        expect(shownRowNames()).toEqual([])

        release()
        await waitFor(() => expect(shownRowNames()).toEqual(['Renewal reminder', 'Sync accounts to CRM']))
    })

    it('keeps the Customer.io import next to the folder view', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true,
            [FEATURE_FLAGS.WORKFLOWS_CUSTOMERIO_IMPORT]: true,
        })
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() => expect(document.querySelector('[data-attr="workflows-folder-toolbar"]')).not.toBeNull())
        expect(document.querySelector('[data-attr="workflows-import-customerio"]')).not.toBeNull()
    })

    it('keeps the loaded rows when a reload fails', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() =>
            expect(document.querySelector('[data-attr="workflows-automation-empty-state-guided-setup"]')).not.toBeNull()
        )
        await userEvent
            .setup()
            .click(
                document.querySelector<HTMLElement>(
                    '[data-attr="workflows-folder-toolbar"] [data-attr="workflows-new-folder"]'
                )!
            )
        expect(document.querySelector('input[data-attr="workflows-new-folder-name"]')).not.toBeNull()
    })

    it('filters the list and writes pills to the URL', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Unfiled' })
        const user = userEvent.setup()
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
        const user = userEvent.setup()
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()[0]).toEqual('Flow 000 even'))

        await user.click(document.querySelector('[aria-label="Next page"]')!)
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
        const user = userEvent.setup()
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
            </Provider>
        )
        await waitFor(() => expect(shownRowNames()).toHaveLength(6))

        const nameHeader = Array.from(
            document.querySelectorAll<HTMLElement>('[data-attr="workflows-list-v2"] .LemonTable__header-content')
        ).find((header) => header.textContent === 'Name')!
        await user.click(nameHeader)
        await user.click(nameHeader)
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
        ['shows Owner when the link names no columns', null, ['', 'Name', 'Status', 'Owner', 'Updated', '', '']],
        [
            'ignores a linked column the list no longer has',
            ['health', 'tags'],
            ['', 'Name', 'Status', 'Health', 'Updated', '', ''],
        ],
        ['shows Kind beside the name', ['type', 'owner'], ['', 'Name', 'Kind', 'Status', 'Owner', 'Updated', '', '']],
    ])('%s', async (_, savedColumns, expectedHeaders) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), {
            q: 'in:Unfiled',
            ...(savedColumns ? { columns: savedColumns.join(',') } : {}),
        })
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
        const user = userEvent.setup()
        render(
            <Provider>
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
                <DndContext>
                    <WorkflowsScene />
                </DndContext>
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
        let droppables: ReturnType<typeof useDndContext>['droppableContainers'] | null

        function DroppableProbe(): null {
            droppables = useDndContext().droppableContainers
            return null
        }

        const renderFolder = async (folder: string, visibleWorkflow: string, filters = ''): Promise<void> => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
            router.actions.push(urls.workflows(), { q: `in:${folder}${filters}` })
            render(
                <Provider>
                    <DndContext>
                        <DroppableProbe />
                        <WorkflowsScene />
                    </DndContext>
                </Provider>
            )
            await waitFor(() => expect(shownRowNames()).toContain(visibleWorkflow))
        }

        beforeEach(() => {
            droppables = null
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
                post: {
                    '/api/projects/:team_id/file_system/': async ({ request }) => {
                        const body = (await request.json()) as { path: string; type: string }
                        const created = { id: `created-${body.path}`, ...body }
                        files.push(created)
                        return [201, created]
                    },
                },
            })
        })

        it('shows workflow descriptions inside a folder as the flat list does', async () => {
            await renderFolder('Billing', 'Welcome series')
            expect(document.querySelector('[data-attr="workflows-list-v2-description"]')).toHaveTextContent(
                'Greets new sign-ups'
            )
        })

        it('opens the template chooser on the kind facet from the folder toolbar', async () => {
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT!,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                    hog_flow: AccessControlLevel.Editor,
                },
            }
            const user = userEvent.setup()
            await renderFolder('Billing', 'Welcome series', ' kind:messaging')
            await user.click(
                document.querySelector('[data-attr="workflows-folder-toolbar"] [data-attr="new-workflow"]')!
            )
            expect(workflowTemplatesLogic.values.typeFilter).toEqual('messaging')
        })

        it('keeps sidebar folders, breadcrumbs and the up row as separate drop targets', async () => {
            await renderFolder('Billing/Cards', 'Renewal reminder')
            const targets = [...(droppables?.values() ?? [])].map((droppable) => ({
                folder: droppable.data.current?.treeId,
                inSidebar: !!droppable.node.current?.closest('[role="tree"]'),
                inBreadcrumbs: !!droppable.node.current?.closest('[data-attr="workflows-folder-toolbar"]'),
            }))
            const countOf = (folder: string, inSidebar: boolean, inBreadcrumbs: boolean): number =>
                targets.filter(
                    (target) =>
                        target.folder === folder &&
                        target.inSidebar === inSidebar &&
                        target.inBreadcrumbs === inBreadcrumbs
                ).length
            expect(countOf('project://', true, false)).toBe(1)
            expect(countOf('project://Billing', true, false)).toBe(1)
            expect(countOf('project://', false, true)).toBe(1)
            expect(countOf('project://Billing', false, true)).toBe(1)
            expect(countOf('project://Billing', false, false)).toBe(1)
        })

        it('lists a subfolder in the open folder after naming it inline', async () => {
            const user = userEvent.setup()
            await renderFolder('Billing', 'Welcome series')
            await user.click(
                document.querySelector<HTMLElement>(
                    '[data-attr="workflows-folder-toolbar"] [data-attr="workflows-new-folder"]'
                )!
            )
            const input = document.querySelector<HTMLInputElement>('input[data-attr="workflows-new-folder-name"]')
            expect(input).not.toBeNull()
            await user.type(input!, 'Invoices{Enter}')
            await waitFor(() =>
                expect(
                    Array.from(document.querySelectorAll('[data-attr="workflows-folder-row"]')).map(
                        (row) => row.textContent
                    )
                ).toContain('Invoices(0)')
            )
            expect(router.values.searchParams.q).toEqual('in:Billing')
            expect(document.querySelector('[role="tree"]')?.textContent).toContain('Invoices')
        })

        const draftInputAfterNewFolder = async (): Promise<HTMLInputElement | null> => {
            await userEvent
                .setup()
                .click(
                    document.querySelector<HTMLElement>(
                        '[data-attr="workflows-folder-toolbar"] [data-attr="workflows-new-folder"]'
                    )!
                )
            return document.querySelector<HTMLInputElement>('input[data-attr="workflows-new-folder-name"]')
        }

        it('shows the inline folder name while a filter narrows the folder', async () => {
            await renderFolder('Billing', 'Welcome series', ' status:active')
            expect(await draftInputAfterNewFolder()).not.toBeNull()
        })

        it('shows the inline folder name from a later page of the folder', async () => {
            workflows = Array.from({ length: 120 }, (_, i) =>
                buildWorkflowRow({ id: `wf-${i}`, name: `Flow ${String(i).padStart(3, '0')}` })
            )
            files = [
                { id: 'billing', path: 'Billing', type: 'folder' },
                ...workflows.map((workflow) => ({
                    id: `file-${workflow.id}`,
                    path: `Billing/${workflow.name}`,
                    type: 'hog_flow',
                    ref: workflow.id,
                })),
            ]
            await renderFolder('Billing', 'Flow 000')
            await userEvent.setup().click(document.querySelector('[aria-label="Next page"]')!)
            await waitFor(() => expect(shownRowNames()).toContain('Flow 119'))
            expect(await draftInputAfterNewFolder()).not.toBeNull()
        })
    })
})

import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, render, screen, waitFor } from '@testing-library/react'
import { getContext } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { MOVE_TIMEOUT_MS, projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { newWorkflowFolder } from '../newWorkflowFolder'
import { newWorkflowLogic } from '../newWorkflowLogic'
import { FOLDER_REQUEST_TIMEOUT_MS, folderNameError, workflowFoldersLogic } from './workflowFoldersLogic'
import { FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'
import { workflowsListV2Logic } from './workflowsListV2Logic'

const EXISTS = 'A folder with this name already exists'

describe('workflowFoldersLogic', () => {
    let logic: ReturnType<typeof workflowFoldersLogic.build>

    const addProjectFiles = (results: FileSystemEntry[]): void =>
        projectTreeDataLogic.actions.addLoadedResults({
            searchTerm: '',
            results,
            hasMore: false,
            lastCount: results.length,
        })

    const templateReceipt = {
        id: 'receipt',
        path: 'Billing/Cards/Receipt',
        type: 'message_template',
        ref: 'template-receipt',
        team_id: MOCK_TEAM_ID,
    }

    const projectFiles = ({ request }: { request: Request }): [number, unknown] => {
        const type = new URL(request.url).searchParams.get('search')?.replace('type:', '')
        const entries = [
            { id: 'billing', path: 'Billing', type: 'folder' },
            { id: 'cards', path: 'Billing/Cards', type: 'folder' },
            { id: 'empty', path: 'Empty', type: 'folder' },
            { id: 'dashboards', path: 'Reports', type: 'folder' },
            { id: 'unfiled', path: 'Unfiled', type: 'folder' },
            { id: 'cohorts', path: 'Unfiled/Cohorts', type: 'folder' },
            { id: 'direct', path: 'Billing/Welcome', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id },
            { id: 'nested', path: 'Billing/Cards/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id },
            templateReceipt,
            {
                id: 'sibling-receipt',
                path: 'Billing/Cards/Staging receipt',
                type: 'message_template',
                ref: 'template-staging',
                team_id: MOCK_TEAM_ID + 1,
            },
        ]
        return [200, paginated(entries.filter((entry) => entry.type === type))]
    }

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [200, []],
                '/api/projects/:team_id/file_system/unfiled/': () => [200, { count: 0 }],
                '/api/projects/:team_id/file_system/folder_counts/': () => [
                    200,
                    { results: [{ folder: 'Reports', count: 1 }] },
                ],
                '/api/projects/:team_id/file_system/': projectFiles,
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    const remount = (): void => {
        logic.unmount()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()
    }

    it('creates a new workflow in the open folder, and stops once the list closes', async () => {
        const newWorkflow = newWorkflowLogic()
        newWorkflow.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openFolder('Billing/Cards')
        await expectLogic(newWorkflow, () => newWorkflow.actions.createEmptyWorkflow()).toFinishAllListeners()
        expect(newWorkflowFolder()).toBe('Billing/Cards')

        logic.unmount()
        router.actions.push(urls.workflows())
        await expectLogic(newWorkflow, () => newWorkflow.actions.createEmptyWorkflow()).toFinishAllListeners()
        expect(newWorkflowFolder()).toBeNull()
        newWorkflow.unmount()
        // A fresh list for `afterEach` to unmount.
        initKeaTests()
        logic = workflowFoldersLogic()
        logic.mount()
    })

    it('opens a project folder with counted subfolders and only its direct workflows', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        expect(logic.values.folderCounts.Billing).toBe(3)
        expect(logic.values.childFolders.map((folder) => folder.path)).toEqual(['Billing/Cards'])
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
        expect(logic.values.folderPaths).not.toContain('Reports')
        expect(logic.values.folderPaths).toContain('Empty')
        expect(logic.values.folderPaths).not.toContain('Unfiled/Cohorts')
    })

    it('places no workflow in any folder, Unfiled included, until the folder scan loads', async () => {
        logic.unmount()
        let releaseScan!: () => void
        const scanHeld = new Promise<void>((resolve) => (releaseScan = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    await scanHeld
                    return projectFiles({ request })
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.rows).toHaveLength(FIXTURE_WORKFLOWS.length))
        const scope = logic.values.folderFacets.find((facet) => facet.key === 'in')!
        const nested = logic.values.folderSearchItems.find((item) => item.id === `workflow:${FIXTURE_WORKFLOWS[1].id}`)!

        logic.actions.openFolder('Unfiled')
        expect(logic.values.folderRows).toEqual([])
        expect(scope.getValues(nested)).toEqual([])

        releaseScan()
        await waitFor(() => expect(logic.values.browserReady).toBe(true))
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[3].id, FIXTURE_WORKFLOWS[2].id])
        logic.actions.openFolder('Billing/Cards')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
    })

    it('offers automation setup only once every workflow page has loaded', async () => {
        logic.unmount()
        let answerLaterPage!: (body: unknown) => void
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.get('offset')
                        ? new Promise((resolve) => (answerLaterPage = (body) => resolve([200, body])))
                        : [
                              200,
                              paginated(
                                  FIXTURE_WORKFLOWS.filter((workflow) => workflow.type === 'messaging'),
                                  'http://localhost/api/projects/997/hog_flows/summaries/?offset=100'
                              ),
                          ],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'kind:automation' })
        logic = workflowFoldersLogic()
        logic.mount()

        await waitFor(() => expect(answerLaterPage).not.toBeUndefined())
        await waitFor(() => expect(logic.values.rows.length).toBeGreaterThan(0))
        expect(logic.values.showsAutomationSetup).toBe(false)

        answerLaterPage(paginated([]))
        await waitFor(() => expect(logic.values.showsAutomationSetup).toBe(true))
    })

    it('opens folders from the loaded index without another folder request', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': () => {
                    requests++
                    return [500, { detail: 'Unavailable' }]
                },
            },
        })
        logic.actions.openFolder('Billing')
        await expectLogic(logic).toFinishAllListeners()
        expect(requests).toBe(0)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
    })

    it("shows this environment's email templates in their open folder and counts, not a sibling's", async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toEqual(['template-receipt'])
        expect(logic.values.folderCounts['Billing/Cards']).toBe(2)
    })

    it('backfills unfiled templates before loading their folder index', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let backfilled = false
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/unfiled/': () => {
                    backfilled = true
                    return [200, { count: 1 }]
                },
                '/api/projects/:team_id/file_system/': ({ request }) => [
                    200,
                    paginated(
                        backfilled && new URL(request.url).searchParams.get('search') === 'type:message_template'
                            ? [
                                  {
                                      id: 'unfiled-email',
                                      type: 'message_template',
                                      ref: 'synthetic-unfiled-email',
                                      path: 'Unfiled/Email templates/Receipt',
                                  },
                              ]
                            : []
                    ),
                ],
            },
        })
        remount()
        await waitFor(() => expect(logic.values.browserReady).toBe(true))
        logic.actions.openFolder('Unfiled')
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toContain('synthetic-unfiled-email')
        expect(logic.values.folderPaths).toContain('Unfiled')
    })

    const showToasts = (): void => {
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
    }

    it('creates a subfolder through the existing project file API', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/': async ({ request }) => [
                    201,
                    { id: 'new-folder', ...((await request.json()) as { path: string; type: string }) },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        await logic.asyncActions.createFolder('Invoices')
        expect(logic.values.folderPaths).toContain('Billing/Invoices')
    })

    it.each([
        ['creates', (name: string) => logic.asyncActions.createFolder(name, 'Billing'), "Couldn't create the folder."],
        [
            'renames',
            (name: string) => logic.asyncActions.renameFolder('Billing/Cards', name),
            "Couldn't rename the folder.",
        ],
    ])("%s a folder only under a name no other product's file uses in that folder", async (_, change, failure) => {
        const dashboards = [
            { id: 'weekly', path: 'Billing/Weekly', type: 'dashboard' },
            { id: 'quoted', path: 'Billing/Quarterly "Report"', type: 'dashboard' },
        ]
        let lookups: Record<string, string>[] = []
        const writes: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const path = params.get('path')
                    if (path === null) {
                        return projectFiles({ request })
                    }
                    lookups.push(Object.fromEntries(params))
                    return [200, paginated(dashboards.filter((entry) => entry.path === path))]
                },
            },
            post: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const body = (await request.json()) as { path: string; type: string }
                    writes.push(body.path)
                    return [201, { id: 'new-folder', ...body }]
                },
                '/api/projects/:team_id/file_system/:id/count/': () => [200, { count: 1 }],
                '/api/projects/:team_id/file_system/:id/move/': async ({ request, params }) => {
                    const path = ((await request.json()) as { new_path: string }).new_path
                    writes.push(path)
                    return [200, { id: params.id, path, type: 'folder' }]
                },
            },
        })
        showToasts()
        await expectLogic(logic).toFinishAllListeners()

        await change('Weekly')
        expect(await screen.findByText(`${failure} This name is already used in this folder.`)).toBeInTheDocument()
        expect(logic.values.folderPaths.map((path) => path.toLowerCase())).not.toContain('billing/weekly')

        await change('Quarterly "Report"')
        expect(lookups.at(-1)?.path).toBe('Billing/Quarterly "Report"')
        expect(writes).toEqual([])

        lookups = []
        await change('a')
        await waitFor(() => expect(logic.values.folderPaths).toContain('Billing/a'))
        expect(lookups).toEqual([{ path: 'Billing/a', limit: '2' }])
        expect(writes).toEqual(['Billing/a'])
    })

    it.each([
        [
            'the reason the server gives',
            400,
            { detail: 'Path has too many levels.' },
            "Couldn't create the folder. Path has too many levels.",
        ],
        ['a retry when the server gives no reason', 500, {}, "Couldn't create the folder. Try again."],
    ])('reports a failed folder creation with %s and allows retry', async (_, status, body, message) => {
        await expectLogic(logic).toFinishAllListeners()
        showToasts()
        useMocks({ post: { '/api/projects/:team_id/file_system/': () => [status, body] } })
        await logic.asyncActions.createFolder('Invoices', 'Billing')
        expect(logic.values.folderCreationError).toBeTruthy()
        expect(await screen.findByText(message)).toBeInTheDocument()
        expect(logic.values.creatingFolder).toBe(false)
    })

    it.each([
        {
            name: 'deletes only an empty project folder without deleting its contents',
            status: 204,
            body: null,
            toast: [],
        },
        {
            name: 'keeps a folder the server reports is not empty',
            status: 409,
            body: { type: 'invalid_request', code: 'directory_not_empty', detail: 'Folder is not empty.' },
            toast: ["Couldn't delete the folder. It still contains project files."],
        },
        {
            name: "keeps a folder and shows the server's reason for any other failure",
            status: 403,
            body: { type: 'authentication_error', code: 'permission_denied', detail: 'You do not have access.' },
            toast: ["Couldn't delete the folder. You do not have access."],
        },
    ])('$name', async ({ status, body, toast }) => {
        let recursive: string | null | undefined
        showToasts()
        useMocks({
            delete: {
                '/api/projects/:team_id/file_system/empty/': ({ request }) => {
                    recursive = new URL(request.url).searchParams.get('recursive')
                    return [status, body]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        await logic.asyncActions.deleteFolder('Empty')
        expect(recursive).toBe('false')
        expect(logic.values.folderPaths.includes('Empty')).toBe(status !== 204)
        await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
        expect(screen.queryAllByText(/^Couldn't delete the folder/).map((element) => element.textContent)).toEqual(
            toast
        )
    })

    it('drops a workflow into Unfiled without creating a new unfiled location', async () => {
        let movedPath: string | undefined
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/direct/move/': async ({ request }) => {
                    const body = (await request.json()) as { new_path: string }
                    movedPath = body.new_path
                    return [200, { id: 'direct', path: body.new_path, type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        await logic.asyncActions.dropFile('project/direct', 'project://Unfiled')
        await expectLogic(logic).toFinishAllListeners()
        await waitFor(() => expect(movedPath).toBe('Unfiled/Workflows/Welcome'))
    })

    it('drops a workflow onto a folder that only exists as a file location', async () => {
        let movedPath: string | undefined
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/direct/move/': async ({ request }) => {
                    const body = (await request.json()) as { new_path: string }
                    movedPath = body.new_path
                    return [200, { id: 'direct', path: body.new_path, type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        addProjectFiles([
            { id: 'archived', path: 'Archive/Old receipt', type: 'message_template', ref: 'template-old' },
        ])
        expect(logic.values.folderPaths).toContain('Archive')
        await logic.asyncActions.dropFile('project/direct', 'project://Archive')
        await waitFor(() => expect(movedPath).toBe('Archive/Welcome'))
    })

    it.each([
        ['lands', 200],
        ['fails', 500],
    ])('moves a dropped file only once until its move %s', async (_, status) => {
        await expectLogic(logic).toFinishAllListeners()
        let releaseMove!: () => void
        const moveHeld = new Promise<void>((resolve) => (releaseMove = resolve))
        const moves: string[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/direct/move/': async ({ request }) => {
                    const body = (await request.json()) as { new_path: string }
                    moves.push(body.new_path)
                    await moveHeld
                    return [
                        status,
                        { id: 'direct', path: body.new_path, type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id },
                    ]
                },
            },
        })
        await logic.asyncActions.dropFile('project/direct', 'project://Billing/Cards')
        await waitFor(() => expect(moves).toEqual(['Billing/Cards/Welcome']))
        await logic.asyncActions.dropFile('project/direct', 'project://Empty')
        releaseMove()
        await waitFor(() => expect(projectTreeDataLogic.values.pendingActions).toEqual([]))
        expect(moves).toEqual(['Billing/Cards/Welcome'])

        await logic.asyncActions.dropFile('project/direct', 'project://Empty')
        await waitFor(() => expect(moves).toEqual(['Billing/Cards/Welcome', 'Empty/Welcome']))
    })

    it('shows files moved directly into Unfiled inside the Unfiled folder', async () => {
        await expectLogic(logic).toFinishAllListeners()
        addProjectFiles([
            { id: 'moved', path: 'Unfiled/Moved receipt', type: 'message_template', ref: 'template-moved' },
        ])
        logic.actions.openFolder('Unfiled')
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toContain('template-moved')
        expect(logic.values.folderCounts.Unfiled).toBe(logic.values.folderFileRows.length)
        const unfiledRows = logic.values.folderRows.map((row) => row.id)

        const scope = logic.values.folderFacets.find((facet) => facet.key === 'in')!
        expect(logic.values.folderFileRows.flatMap((row) => scope.getValues(row))).not.toContain('Unfiled/Workflows')
        logic.actions.setValue({ filters: [{ facet: 'in', value: 'Unfiled/Workflows', negated: false }], text: '' })
        expect(logic.values.folderRows.map((row) => row.id)).toEqual(unfiledRows)
    })

    it.each([
        ['ignores a shortcut-only folder', [{ id: 'shortcut', path: 'Z/Spring promo', shortcut: true }], 'Z', []],
        [
            'places a workflow by its own file, not a shortcut that sorts after it',
            [
                { id: 'original', path: 'Campaigns/Spring promo', shortcut: false },
                { id: 'shortcut', path: 'Z/Spring promo', shortcut: true },
            ],
            'Campaigns',
            [FIXTURE_WORKFLOWS[3].id],
        ],
    ])('%s', async (_, files, folder, shown) => {
        await expectLogic(logic).toFinishAllListeners()
        addProjectFiles(files.map((file) => ({ ...file, type: 'hog_flow', ref: FIXTURE_WORKFLOWS[3].id })))
        logic.actions.openFolder(folder)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual(shown)
    })

    it("asks only for workflow files and folders, and counts other products' files per folder", async () => {
        await expectLogic(logic).toFinishAllListeners()
        const searches = new Set<string | null>()
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    searches.add(new URL(request.url).searchParams.get('search'))
                    return projectFiles({ request })
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadBrowser()).toFinishAllListeners()

        expect(searches).toEqual(new Set(['type:folder', 'type:hog_flow', 'type:message_template']))
        expect(logic.values.folderPaths).not.toContain('Reports')
        logic.actions.openFolder('Reports')
        expect(logic.values.otherProductFileCount).toBe(1)
    })

    it('hides empty folders inside a branch that only holds other products', async () => {
        await expectLogic(logic).toFinishAllListeners()
        addProjectFiles([{ id: 'drafts', path: 'Reports/Drafts', type: 'folder' }])
        expect(logic.values.folderPaths).not.toContain('Reports')
        expect(logic.values.folderPaths).not.toContain('Reports/Drafts')
        expect(logic.values.folderPaths).toContain('Empty')
    })

    it('matches email templates when either of two kind pills applies', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setValue({
            filters: [
                { facet: 'kind', value: 'messaging', negated: false },
                { facet: 'kind', value: 'email-template', negated: false },
            ],
            text: '',
        })
        expect(logic.values.matchingTemplates.map((entry) => entry.ref)).toContain('template-receipt')
    })

    it.each([
        [
            'a parent folder in the sidebar or the up row',
            'project/nested',
            'project://Billing',
            'nested',
            'Billing/Renewal',
        ],
        ['the Project files breadcrumb', 'project/direct', 'project://', 'direct', 'Welcome'],
        ['the tree background', 'project/direct', '', 'direct', 'Welcome'],
    ])('drops a workflow onto %s', async (_, activeId, overId, fileId, expectedPath) => {
        let movedPath: string | undefined
        useMocks({
            post: {
                [`/api/projects/:team_id/file_system/${fileId}/move/`]: async ({ request }) => {
                    const body = (await request.json()) as { new_path: string }
                    movedPath = body.new_path
                    return [200, { id: fileId, path: body.new_path, type: 'hog_flow' }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        await logic.asyncActions.dropFile(activeId, overId)
        await waitFor(() => expect(movedPath).toBe(expectedPath))
    })

    it('names a new subfolder inline and lists it in the open folder', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/': async ({ request }) => [
                    201,
                    { id: 'new-folder', ...((await request.json()) as { path: string; type: string }) },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.startFolderDraft('Billing')
        expect(logic.values.currentFolder).toBe('Billing')
        expect(logic.values.folderDraftError).toBe('Give the folder a name')
        logic.actions.setFolderDraftName('cards')
        expect(logic.values.folderDraftError).toBe('A folder with this name already exists')
        logic.actions.setFolderDraftName('Invoices')
        expect(logic.values.folderDraftError).toBeNull()
        await logic.asyncActions.submitFolderDraft()
        expect(logic.values.folderDraft).toBeNull()
        expect(logic.values.currentFolder).toBe('Billing')
        expect(logic.values.childFolders.map((folder) => folder.path)).toContain('Billing/Invoices')
        expect(logic.values.expandedFolders).toContain('project://Billing')
    })

    it('keeps the inline folder name when creation fails', async () => {
        useMocks({ post: { '/api/projects/:team_id/file_system/': () => [500, { detail: 'Unavailable' }] } })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.startFolderDraft('Billing')
        logic.actions.setFolderDraftName('Invoices')
        await logic.asyncActions.submitFolderDraft()
        expect(logic.values.folderDraft).toEqual({ parent: 'Billing', name: 'Invoices' })
        expect(logic.values.creatingFolder).toBe(false)
    })

    it('keeps folder scope and counts after the shared tree prunes its collapsed cache', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        const { projectTreeDataLogic } = await import('~/layout/panel-layout/ProjectTree/projectTreeDataLogic')
        expect(logic.values.folderPaths).not.toContain('Reports')
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderCounts.Billing).toBe(3)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
        expect(logic.values.folderPaths).not.toContain('Reports')
    })

    it('puts back the files the shared tree prunes without asking the server again', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        const requests: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    requests.push(request.url)
                    return [200, paginated([])]
                },
            },
        })
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        expect(requests).toEqual([])
        expect(logic.values.browserReadyLoading).toBe(false)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toEqual(['template-receipt'])
    })

    it('puts back the renamed file, not its old name, after the shared tree refreshes it and prunes', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        const renamed = {
            id: 'receipt',
            path: 'Billing/Cards/Receipt v2',
            type: 'message_template',
            ref: 'template-receipt',
            team_id: MOCK_TEAM_ID,
        }
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) =>
                    new URL(request.url).searchParams.get('ref') === 'template-receipt'
                        ? [200, paginated([renamed])]
                        : [200, paginated([])],
            },
        })
        await projectTreeDataLogic.asyncActions.syncTypeAndRef('message_template', 'template-receipt', true)
        logic.actions.openFolder('Empty')
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderTemplates.map((entry) => entry.path)).toEqual(['Billing/Cards/Receipt v2'])
    })

    it.each([
        [
            'a workflow',
            async (): Promise<void> => {
                const moved = { id: 'nested', path: 'Billing/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id }
                useMocks({
                    get: {
                        '/api/projects/:team_id/file_system/': ({ request }) =>
                            new URL(request.url).searchParams.get('ref') === moved.ref
                                ? [200, paginated([moved])]
                                : [200, paginated([])],
                    },
                })
                await projectTreeDataLogic.asyncActions.syncTypeAndRef('hog_flow', moved.ref, true)
            },
            ['Billing/Cards/Receipt'],
            [],
        ],
        [
            'several files of one folder',
            (): void =>
                addProjectFiles([
                    { id: 'nested', path: 'Billing/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id },
                    { ...templateReceipt, path: 'Billing/Receipt' },
                ]),
            [],
            ['Billing/Receipt'],
        ],
    ])(
        'shows %s only in the new folder after the shared tree refreshes a move made elsewhere',
        async (_, refresh, cardsTemplates, billingTemplates) => {
            await expectLogic(logic).toFinishAllListeners()
            await refresh()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openFolder('Billing/Cards')
            expect(logic.values.folderRows.map((row) => row.id)).toEqual([])
            expect(logic.values.folderTemplates.map((entry) => entry.path)).toEqual(cardsTemplates)
            logic.actions.openFolder('Billing')
            expect(logic.values.folderRows.map((row) => row.id)).toEqual([
                FIXTURE_WORKFLOWS[1].id,
                FIXTURE_WORKFLOWS[0].id,
            ])
            expect(logic.values.folderTemplates.map((entry) => entry.path)).toEqual(billingTemplates)
        }
    )

    it.each([
        [
            'keeps a rename the shared tree refreshes while an older folder scan is still loading',
            'Billing/Cards/Receipt v2',
            () => projectTreeDataLogic.asyncActions.syncTypeAndRef('message_template', 'template-receipt', true),
        ],
        [
            'keeps a file out once a full folder reload drops it while an older folder scan is still loading',
            null,
            () =>
                projectTreeDataLogic.actions.loadFolderSuccess(
                    'Billing/Cards',
                    [{ id: 'nested', path: 'Billing/Cards/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id }],
                    false,
                    1,
                    true
                ),
        ],
    ])('%s', async (_name, newPath: string | null, refreshTree: () => unknown) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        let receiptPath: string | null = 'Billing/Cards/Receipt'
        let releaseScan!: () => void
        const scanHeld = new Promise<void>((resolve) => (releaseScan = resolve))
        let scanStarted = false
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const receipts = receiptPath ? [{ ...templateReceipt, path: receiptPath }] : []
                    if (params.get('ref') === 'template-receipt') {
                        return [200, paginated(receipts)]
                    }
                    const search = params.get('search')
                    if (search === 'type:message_template' && !scanStarted) {
                        scanStarted = true
                        await scanHeld
                    }
                    return [200, paginated(search === 'type:message_template' ? receipts : [])]
                },
            },
        })
        logic.actions.loadBrowser()
        await waitFor(() => expect(scanStarted).toBe(true))
        receiptPath = newPath
        await refreshTree()
        releaseScan()
        await waitFor(() => expect(logic.values.browserReadyLoading).toBe(false))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.folderTemplates.map((entry) => entry.path)).toEqual(newPath ? [newPath] : [])
    })

    it.each([
        ['restores a folder the shared tree cut to its first page from workflow file scans alone', 200, false],
        ['keeps the cached files of a cut folder and offers a retry when its scan fails', 500, true],
        ['keeps the cached files of a cut folder and offers a retry when its scan stalls', null, true],
    ])('%s', async (_name, scanStatus, offersRetry) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        const requests: URLSearchParams[] = []
        const welcome = { id: 'direct', path: 'Billing/Welcome', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id }
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    if (scanStatus === null) {
                        return new Promise(() => {})
                    }
                    if (params.get('parent') === 'Billing') {
                        // A mixed folder: the indexed workflow sits behind pages of another product's files.
                        const offset = Number(params.get('offset'))
                        const notes = Array.from({ length: 101 }, (_, index) => ({
                            id: `notes-${offset + index}`,
                            path: `Billing/Notes ${offset + index}`,
                            type: 'notebook',
                            ref: `synthetic-notes-${offset + index}`,
                        }))
                        return [200, paginated(offset < 200 ? notes : [welcome])]
                    }
                    return scanStatus === 200 ? projectFiles({ request }) : [scanStatus, { detail: 'Unavailable' }]
                },
            },
        })
        jest.useFakeTimers()
        try {
            projectTreeDataLogic.actions.loadFolderSuccess(
                'Billing',
                [{ id: 'cards', path: 'Billing/Cards', type: 'folder' }],
                true,
                1,
                true
            )
            await jest.advanceTimersByTimeAsync(FOLDER_REQUEST_TIMEOUT_MS)
        } finally {
            jest.useRealTimers()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(new Set(requests.map((params) => params.get('search')))).toEqual(
            new Set(['type:folder', 'type:hog_flow', 'type:message_template'])
        )
        expect(logic.values.browserReadyLoading).toBe(false)
        expect(logic.values.browserLoadFailed).toBe(offersRetry)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
    })

    it('forgets a file a fully reloaded folder no longer lists', async () => {
        await expectLogic(logic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadFolderSuccess(
            'Billing',
            [{ id: 'cards', path: 'Billing/Cards', type: 'folder' }],
            false,
            1,
            true
        )
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.placements?.[`hog_flow::${FIXTURE_WORKFLOWS[0].id}`]).toBeUndefined()
        expect(logic.values.placements?.[`hog_flow::${FIXTURE_WORKFLOWS[1].id}`]?.path).toEqual('Billing/Cards/Renewal')
    })

    it.each([
        [
            'deleted',
            (): void =>
                projectTreeDataLogic.actions.deleteSavedItem({ id: 'cards', path: 'Billing/Cards', type: 'folder' }),
        ],
        [
            'gone after a full reload',
            (): void => {
                useMocks({
                    get: {
                        '/api/projects/:team_id/file_system/': ({ request }) =>
                            new URL(request.url).searchParams.get('search') === 'type:folder'
                                ? [200, paginated([{ id: 'billing', path: 'Billing', type: 'folder' }])]
                                : [200, paginated([])],
                    },
                })
                logic.actions.loadBrowser()
            },
        ],
        [
            'gone from a reload of its parent',
            (): void => {
                useMocks({
                    get: {
                        '/api/projects/:team_id/file_system/': ({ request }) =>
                            new URL(request.url).searchParams.get('parent') === 'Billing'
                                ? [
                                      200,
                                      paginated([
                                          {
                                              id: 'direct',
                                              path: 'Billing/Welcome',
                                              type: 'hog_flow',
                                              ref: FIXTURE_WORKFLOWS[0].id,
                                          },
                                      ]),
                                  ]
                                : [200, paginated([])],
                    },
                })
                projectTreeDataLogic.actions.loadFolder('Billing', true)
            },
        ],
    ])('keeps a folder branch away after it is %s and the shared tree prunes', async (_, loseBranch) => {
        await expectLogic(logic).toFinishAllListeners()
        loseBranch()
        await expectLogic(logic).toFinishAllListeners()
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        expect(
            projectTreeDataLogic.values.savedItems.filter((entry) => entry.path.startsWith('Billing/Cards'))
        ).toEqual([])
        expect(logic.values.folderPaths).not.toContain('Billing/Cards')
    })

    it('keeps a folder created while the folder index loads', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let releaseWorkflows!: () => void
        const workflowsHeld = new Promise<void>((resolve) => (releaseWorkflows = resolve))
        let workflowsRequested = false
        const created: FileSystemEntry[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search')
                    if (search === 'type:hog_flow') {
                        workflowsRequested = true
                        await workflowsHeld
                    }
                    return [200, paginated(search === 'type:folder' ? created : [])]
                },
            },
            post: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const { path } = (await request.json()) as { path: string }
                    created.push({ id: 'drafts', path, type: 'folder' })
                    return [200, created[0]]
                },
            },
        })
        logic.actions.loadBrowser()
        await waitFor(() => expect(workflowsRequested).toBe(true))
        logic.actions.createFolder('Drafts', '')
        await waitFor(() => expect(created).toHaveLength(1))
        releaseWorkflows()
        await expectLogic(logic).toFinishAllListeners()
        await waitFor(() => expect(logic.values.browserReadyLoading).toBe(false))
        expect(logic.values.folderPaths).toContain('Drafts')
    })

    it('offers a retry when files keep changing through every folder load', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let changes = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    if (new URL(request.url).searchParams.get('search') === 'type:hog_flow') {
                        changes++
                        projectTreeDataLogic.actions.createSavedItem({
                            id: `draft-${changes}`,
                            path: `Draft ${changes}`,
                            type: 'folder',
                        })
                    }
                    return [200, paginated([])]
                },
            },
        })
        logic.actions.loadBrowser()
        await waitFor(() => expect(logic.values.browserReadyLoading).toBe(false))
        expect(logic.values.browserLoadFailed).toBe(true)
    })

    it.each([
        ['the unfiled backfill', '/api/projects/:team_id/file_system/unfiled/'],
        ['a file list page', '/api/projects/:team_id/file_system/'],
    ])('offers a retry when %s stalls', async (_name, stalled) => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ get: { [stalled]: () => new Promise(() => {}) } })
        jest.useFakeTimers()
        try {
            remount()
            await jest.advanceTimersByTimeAsync(FOLDER_REQUEST_TIMEOUT_MS)
            expect(logic.values.browserReadyLoading).toBe(false)
            expect(logic.values.browserLoadFailed).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })

    it("moves workflow files and drops folders and other products' files to match a full reload", async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderPaths).not.toContain('Reports')
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/folder_counts/': () => [200, { results: [] }],
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('search')
                    if (type === 'type:folder') {
                        return [200, paginated([{ id: 'dashboards', path: 'Reports', type: 'folder' }])]
                    }
                    return [
                        200,
                        paginated(
                            type === 'type:hog_flow'
                                ? [
                                      {
                                          id: 'direct',
                                          path: 'Archive/Welcome',
                                          type: 'hog_flow',
                                          ref: FIXTURE_WORKFLOWS[0].id,
                                      },
                                  ]
                                : []
                        ),
                    ]
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadBrowser()).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        expect(logic.values.folderRows.map((row) => row.id)).not.toContain(FIXTURE_WORKFLOWS[0].id)
        logic.actions.openFolder('Archive')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
        expect(logic.values.folderPaths).not.toContain('Empty')
        expect(logic.values.folderPaths).toContain('Reports')
    })

    it('rejects a folder name that only another product uses', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderPaths).not.toContain('Reports')
        logic.actions.startFolderDraft('')
        logic.actions.setFolderDraftName('reports')
        expect(logic.values.folderDraftError).toBe(EXISTS)
    })

    it('replaces many files of one folder in the shared tree with one removal and one merge', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const files = (prefix: string): FileSystemEntry[] =>
            Array.from({ length: 40 }, (_, index) => ({
                id: `${prefix}-${index}`,
                path: `Billing/${prefix} workflow ${index}`,
                type: 'hog_flow',
                ref: `${prefix}-ref-${index}`,
            }))
        const stale = files('stale')
        const fresh = files('fresh')
        addProjectFiles(stale)
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search')
                    return [
                        200,
                        paginated(
                            search === 'type:hog_flow'
                                ? fresh
                                : search === 'type:folder'
                                  ? [{ id: 'billing', path: 'Billing', type: 'folder' }]
                                  : []
                        ),
                    ]
                },
            },
        })
        const billingIds = (): string[] =>
            (projectTreeDataLogic.values.folders['Billing'] ?? []).map((entry) => entry.id).sort()
        let removals = 0
        let previous = billingIds().length
        const unsubscribe = getContext().store.subscribe(() => {
            const current = billingIds().length
            removals += current < previous ? 1 : 0
            previous = current
        })

        await expectLogic(logic, () => logic.actions.loadBrowser()).toFinishAllListeners()
        unsubscribe()

        expect(billingIds()).toEqual(fresh.map((entry) => entry.id).sort())
        expect(removals).toBe(1)
    })

    it("paints the folders before other products' files load, and checks folder names once they have", async () => {
        logic.unmount()
        let releaseOtherFiles!: () => void
        const otherFilesHeld = new Promise<void>((resolve) => (releaseOtherFiles = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/folder_counts/': async () => {
                    await otherFilesHeld
                    return [200, { results: [{ folder: 'Billing', count: 2 }] }]
                },
                '/api/projects/:team_id/file_system/': ({ request }) => [
                    200,
                    paginated(
                        new URL(request.url).searchParams.get('search') === 'type:folder'
                            ? [{ id: 'billing', path: 'Billing', type: 'folder' }]
                            : []
                    ),
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()

        await waitFor(() => expect(logic.values.browserReady).toBe(true))
        expect(logic.values.folderPaths).toContain('Billing')
        expect(logic.values.otherFileCounts).toBeNull()
        logic.actions.startFolderDraft('')
        logic.actions.setFolderDraftName('billing')
        expect(logic.values.folderDraftError).toBe('Checking existing folder names. Try again in a moment.')

        releaseOtherFiles()
        await waitFor(() => expect(logic.values.otherFileCounts).toEqual({ Billing: 2 }))
        expect(logic.values.folderDraftError).toBe(EXISTS)
    })

    it("checks folder names only once the folder scan has loaded, even when other products' files load first", async () => {
        logic.unmount()
        let releaseFolders!: () => void
        const foldersHeld = new Promise<void>((resolve) => (releaseFolders = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search') ?? ''
                    if (search === 'type:folder') {
                        await foldersHeld
                        return [200, paginated([{ id: 'billing', path: 'Billing', type: 'folder' }])]
                    }
                    return [200, paginated([])]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()

        await waitFor(() => expect(logic.values.otherFileCounts).not.toBeNull())
        logic.actions.startFolderDraft('')
        logic.actions.setFolderDraftName('billing')
        expect(logic.values.folderDraftError).toBe('Checking existing folder names. Try again in a moment.')

        releaseFolders()
        await waitFor(() => expect(logic.values.folderDraftError).toBe(EXISTS))
    })

    it.each([
        ['a case-only rename of the same folder', 'billing', 'Billing', ['Billing'], null],
        ['a case-only rename onto a separate folder', 'billing', 'Billing', ['Billing', 'billing'], EXISTS],
        ['a new folder that differs only in case', 'billing', undefined, ['Billing'], EXISTS],
    ])('validates %s', (_, name, renaming, paths, error) => {
        expect(folderNameError(name, '', paths, renaming)).toEqual(error)
    })

    it("counts other products' files at a folder's new path when it moves while they load", async () => {
        await waitFor(() => expect(logic.values.otherFileCounts).not.toBeNull())
        let releaseCounts!: () => void
        const countsHeld = new Promise<void>((resolve) => (releaseCounts = resolve))
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/folder_counts/': async () => {
                    requests++
                    if (requests === 1) {
                        await countsHeld
                        return [200, { results: [{ folder: 'Reports', count: 1 }] }]
                    }
                    return [200, { results: [{ folder: 'Archive', count: 1 }] }]
                },
            },
        })
        logic.actions.loadOtherFiles()
        await waitFor(() => expect(requests).toBe(1))
        projectTreeDataLogic.actions.movedItem(
            { id: 'dashboards', path: 'Archive', type: 'folder' },
            'Reports',
            'Archive'
        )
        releaseCounts()
        await waitFor(() => expect(logic.values.otherFileCountsLoading).toBe(false))
        expect(logic.values.otherFileCounts).toEqual({ Archive: 1 })
    })

    it('files unfiled project files once, not again for each recovery scan', async () => {
        await waitFor(() => expect(logic.values.browserReady).toBe(true))
        let unfiledRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/unfiled/': () => {
                    unfiledRequests++
                    return [200, { count: 0 }]
                },
            },
        })
        logic.actions.loadBrowser()
        await waitFor(() => expect(logic.values.browserReadyLoading).toBe(false))
        expect(logic.values.browserReady).toBe(true)
        expect(unfiledRequests).toBe(0)
    })

    it.each([
        ['every scan fails', false, true],
        ["only the other products' scan fails, before the folder scans answer", true, false],
    ])('reports a failed scan when %s, and recovers on retry', async (_, folderScansSucceed, blocksContents) => {
        await expectLogic(logic).toFinishAllListeners()
        let releaseFolderScans!: () => void
        const folderScansHeld = new Promise<void>((resolve) => (releaseFolderScans = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/folder_counts/': () => [500, { detail: 'Unavailable' }],
                '/api/projects/:team_id/file_system/': async () => {
                    await folderScansHeld
                    return folderScansSucceed ? [200, paginated([])] : [500, { detail: 'Unavailable' }]
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadBrowser()).toDispatchActions(['loadOtherFilesFailure'])
        releaseFolderScans()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.browserLoadFailed).toBe(blocksContents)
        expect(logic.values.otherFilesScanFailed).toBe(true)
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': () => [200, paginated([])],
                '/api/projects/:team_id/file_system/folder_counts/': () => [200, { results: [] }],
            },
        })
        await expectLogic(logic, () =>
            blocksContents ? logic.actions.loadBrowser() : logic.actions.loadOtherFiles()
        ).toFinishAllListeners()
        expect(logic.values.browserLoadFailed).toBe(false)
        expect(logic.values.otherFilesScanFailed).toBe(false)
    })

    it('restores folders when the project tree prunes during an index refresh', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let release: () => void = () => {}
        const paused = new Promise<void>((resolve) => {
            release = resolve
        })
        let waiting = false
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const type = new URL(request.url).searchParams.get('search')
                    if (type === 'type:hog_flow' && !waiting) {
                        waiting = true
                        await paused
                    }
                    return [
                        200,
                        paginated(
                            type === 'type:folder' ? [{ id: 'cards', path: 'Billing/Cards', type: 'folder' }] : []
                        ),
                    ]
                },
            },
        })
        logic.actions.loadBrowser()
        await waitFor(() => expect(waiting).toBe(true))
        const { projectTreeDataLogic } = await import('~/layout/panel-layout/ProjectTree/projectTreeDataLogic')
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        release()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderPaths).toContain('Billing/Cards')
    })

    it('opens the folder a workflows link scopes to, and keeps an opened folder in the URL', async () => {
        logic.unmount()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: 'in:Billing' })
        logic = workflowFoldersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentFolder).toBe('Billing')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])

        logic.actions.openFolder('Billing/Cards')
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams.q).toBe('in:Billing/Cards')
        expect(logic.values.currentFolder).toBe('Billing/Cards')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
    })

    it.each(['in', 'path', 'folder', 'Folder'])('restores a project folder from %s: in the URL', async (key) => {
        logic.unmount()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { q: `${key}:Billing status:active` })
        logic = workflowFoldersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(workflowsListV2Logic.values.value.filters).toEqual([
            { facet: 'in', value: 'Billing', negated: false },
            { facet: 'status', value: 'active', negated: false },
        ])
        expect(router.values.searchParams.q).toBe('in:Billing status:active')
    })

    it('reveals the scoped folder and its subfolders when opened from a link', async () => {
        logic.unmount()
        projectTreeDataLogic.mount()
        workflowsListV2Logic.mount()
        workflowsListV2Logic.actions.setValue({
            filters: [{ facet: 'in', value: 'Billing', negated: false }],
            text: '',
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.expandedFolders).toContain('project://Billing')
    })

    it.each([
        [
            'here',
            (): void =>
                projectTreeDataLogic.actions.movedItem(
                    { id: 'billing', path: 'Billing', type: 'folder' },
                    'Billing',
                    'Archive'
                ),
        ],
        [
            'in another tab and the shared tree reloads its parent',
            (): void => {
                const rootFolders = [
                    { id: 'billing', path: 'Archive', type: 'folder' },
                    { id: 'empty', path: 'Empty', type: 'folder' },
                    { id: 'dashboards', path: 'Reports', type: 'folder' },
                    { id: 'unfiled', path: 'Unfiled', type: 'folder' },
                ]
                projectTreeDataLogic.actions.loadFolderSuccess('', rootFolders, false, rootFolders.length, true)
            },
        ],
    ])('follows the open folder, with its files, when an ancestor is renamed %s', async (_, rename) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing/Cards')
        let shortcutLoads = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': () => {
                    shortcutLoads++
                    return [200, paginated([])]
                },
            },
        })

        rename()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()

        expect(logic.values.currentFolder).toBe('Archive/Cards')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.folderTemplates.map((entry) => entry.path)).toEqual(['Archive/Cards/Receipt'])
        expect(logic.values.folderPaths).not.toContain('Billing/Cards')
        // Pins follow a moved folder through one reload, so a rename is applied to the tree once.
        expect(shortcutLoads).toBe(1)
    })

    it.each([
        ['after it moves', [{ folder: 'Reports', count: 1 }], 1],
        [
            'of both folders after it moves onto another',
            [
                { folder: 'Reports', count: 2 },
                { folder: 'Old', count: 3 },
            ],
            5,
        ],
    ])("still counts other products' files in a folder %s, and still hides it", async (_, counts, expected) => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:team_id/file_system/folder_counts/': () => [200, { results: counts }] } })
        await expectLogic(logic, () => logic.actions.loadOtherFiles()).toFinishAllListeners()

        projectTreeDataLogic.actions.movedItem({ id: 'dashboards', path: 'Reports', type: 'folder' }, 'Reports', 'Old')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Old')

        expect(logic.values.otherProductFileCount).toBe(expected)
        expect(logic.values.folderPaths).not.toContain('Old')
    })

    it('refuses a second change to a folder or its subfolders until its rename lands, then creates a drafted folder at the new path', async () => {
        await expectLogic(logic).toFinishAllListeners()
        showToasts()
        let releaseMove!: () => void
        const moveHeld = new Promise<void>((resolve) => (releaseMove = resolve))
        const moves: string[] = []
        const created: string[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const body = (await request.json()) as { path: string; type: string }
                    created.push(body.path)
                    return [201, { id: 'new-folder', ...body }]
                },
                '/api/projects/:team_id/file_system/:id/count/': () => [200, { count: 3 }],
                '/api/projects/:team_id/file_system/:id/move/': async ({ request, params }) => {
                    const body = (await request.json()) as { new_path: string }
                    moves.push(body.new_path)
                    await moveHeld
                    return [200, { id: params.id, path: body.new_path, type: 'folder' }]
                },
            },
        })
        logic.actions.renameFolder('Billing', 'Invoices')
        await waitFor(() => expect(moves).toEqual(['Invoices']))
        expect(logic.values.folderMutationDisabledReason('Billing')).not.toBeNull()
        expect(logic.values.folderMutationDisabledReason('Billing/Cards')).not.toBeNull()
        expect(logic.values.folderMutationDisabledReason('Empty')).toBeNull()

        logic.actions.renameFolder('Billing', 'Accounts')
        logic.actions.renameFolder('Billing/Cards', 'Debit')
        logic.actions.startFolderDraft('Billing/Cards')
        logic.actions.setFolderDraftName('Weekly')
        await logic.asyncActions.submitFolderDraft()
        await logic.asyncActions.dropFile('project/direct', 'project://Billing/Cards')
        expect(
            await screen.findByText("Couldn't create the folder. Wait until this folder finishes moving.")
        ).toBeInTheDocument()
        expect(
            await screen.findByText("Couldn't move the file. Wait until this folder finishes moving.")
        ).toBeInTheDocument()

        const unmountMoveTo = moveToLogic.mount()
        logic.actions.openFolder('Billing')
        logic.actions.toggleSelectedFile(`workflow:${FIXTURE_WORKFLOWS[0].id}`)
        await logic.asyncActions.dropFile('project/direct', 'project://')
        expect(
            await screen.findByText("Couldn't move the file. Wait until its folder finishes moving.")
        ).toBeInTheDocument()
        logic.actions.moveSelectedFiles()
        logic.actions.moveFileToFolder(templateReceipt)
        await logic.asyncActions.moveWorkflowToFolder(FIXTURE_WORKFLOWS[1].id)
        expect(moveToLogic.values.isOpen).toBe(false)
        unmountMoveTo()
        releaseMove()
        await waitFor(() => expect(logic.values.folderMutationDisabledReason('Invoices')).toBeNull())
        await expectLogic(logic).toFinishAllListeners()

        expect(moves).toEqual(['Invoices'])
        expect(created).toEqual([])
        expect(logic.values.folderPaths).toEqual(expect.arrayContaining(['Invoices', 'Invoices/Cards']))
        expect(logic.values.folderPaths).not.toContain('Billing/Cards')

        await logic.asyncActions.submitFolderDraft()
        expect(created).toEqual(['Invoices/Cards/Weekly'])
    })

    it('releases a folder rename when counting the folder stalls', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const moves: string[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/:id/count/': () => new Promise(() => {}),
                '/api/projects/:team_id/file_system/:id/move/': async ({ request }) => {
                    moves.push(((await request.json()) as { new_path: string }).new_path)
                    return [200, {}]
                },
            },
        })
        jest.useFakeTimers()
        try {
            logic.actions.renameFolder('Billing', 'Invoices')
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.folderMutationDisabledReason('Billing')).not.toBeNull()
            await jest.advanceTimersByTimeAsync(MOVE_TIMEOUT_MS)
            expect(logic.values.folderMutationDisabledReason('Billing')).toBeNull()
            expect(moves).toEqual([])
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        {
            change: 'creating',
            start: () => logic.actions.createFolder('Invoices', 'Billing'),
            pending: () => logic.values.creatingFolder,
            toast: "Couldn't create the folder. Try again.",
        },
        {
            change: 'deleting',
            start: () => logic.actions.deleteFolder('Empty'),
            pending: () => logic.values.folderActionPending,
            toast: "Couldn't delete the folder. Try again.",
        },
    ])('allows another folder change after $change a folder stalls', async ({ start, pending, toast }) => {
        await expectLogic(logic).toFinishAllListeners()
        showToasts()
        useMocks({
            post: { '/api/projects/:team_id/file_system/': () => new Promise(() => {}) },
            delete: { '/api/projects/:team_id/file_system/empty/': () => new Promise(() => {}) },
        })
        jest.useFakeTimers()
        try {
            start()
            await jest.advanceTimersByTimeAsync(0)
            expect(pending()).toBe(true)
            await jest.advanceTimersByTimeAsync(FOLDER_REQUEST_TIMEOUT_MS)
            expect(pending()).toBe(false)
        } finally {
            jest.useRealTimers()
        }
        expect(await screen.findByText(toast)).toBeInTheDocument()
    })

    it('allows Move to… again after the workflow lookup stalls', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const unmountMoveTo = moveToLogic.mount()
        const workflowId = FIXTURE_WORKFLOWS[2].id
        let stalled = true
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (!params.get('ref') && !params.get('search')?.includes(`ref:${workflowId}`)) {
                        return projectFiles({ request })
                    }
                    const file = { id: 'sync', path: 'Ops/Sync accounts to CRM', type: 'hog_flow', ref: workflowId }
                    return stalled ? new Promise(() => {}) : [200, paginated([file])]
                },
            },
        })
        jest.useFakeTimers()
        try {
            logic.actions.moveWorkflowToFolder(workflowId)
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.movingWorkflowId).toBe(workflowId)
            await jest.advanceTimersByTimeAsync(FOLDER_REQUEST_TIMEOUT_MS)
            expect(logic.values.movingWorkflowId).toBeNull()
        } finally {
            jest.useRealTimers()
        }

        stalled = false
        await logic.asyncActions.moveWorkflowToFolder(workflowId)
        expect(moveToLogic.values.movingItems.map((entry) => entry.path)).toEqual(['Ops/Sync accounts to CRM'])
        unmountMoveTo()
    })

    it('refuses Move to… for a file whose earlier move is still in flight', async () => {
        await expectLogic(logic).toFinishAllListeners()
        showToasts()
        let releaseMove!: () => void
        const moveHeld = new Promise<void>((resolve) => (releaseMove = resolve))
        const renewal = { id: 'nested', path: 'Billing/Cards/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id }
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) =>
                    new URL(request.url).searchParams.get('search')?.includes('ref:')
                        ? [200, paginated([renewal])]
                        : projectFiles({ request }),
            },
            post: {
                '/api/projects/:team_id/file_system/:id/move/': async ({ request }) => {
                    const body = (await request.json()) as { new_path: string }
                    await moveHeld
                    return [200, { ...renewal, path: body.new_path }]
                },
            },
        })
        const unmountMoveTo = moveToLogic.mount()
        logic.actions.openFolder('Billing/Cards')
        await logic.asyncActions.dropFile('project/nested', 'project://Billing')
        await waitFor(() => expect(logic.values.pendingFileMoveIds).toEqual(['nested']))

        logic.actions.moveFileToFolder(renewal)
        logic.actions.toggleSelectedFile(`workflow:${FIXTURE_WORKFLOWS[1].id}`)
        logic.actions.moveSelectedFiles()
        await logic.asyncActions.moveWorkflowToFolder(FIXTURE_WORKFLOWS[1].id)
        expect(moveToLogic.values.isOpen).toBe(false)
        expect(await screen.findAllByText("Couldn't move the file. Wait until it finishes moving.")).not.toHaveLength(0)

        releaseMove()
        await waitFor(() => expect(logic.values.pendingFileMoveIds).toEqual([]))
        logic.actions.moveFileToFolder({ ...renewal, path: 'Billing/Renewal' })
        expect(moveToLogic.values.isOpen).toBe(true)
        unmountMoveTo()
    })

    it.each([
        { outcome: 'resolves', answer: (): [number, unknown] => [200, paginated([])] },
        { outcome: 'fails', answer: (): [number, unknown] => [500, {}] },
    ])('drops a workflow lookup that $outcome after the list unmounts', async ({ answer }) => {
        await expectLogic(logic).toFinishAllListeners()
        showToasts()
        let releaseLookup!: () => void
        const lookupHeld = new Promise<void>((resolve) => (releaseLookup = resolve))
        let lookups = 0
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    if (!new URL(request.url).searchParams.get('search')?.includes('ref:')) {
                        return projectFiles({ request })
                    }
                    lookups += 1
                    await lookupHeld
                    return answer()
                },
            },
        })
        const unmountMoveTo = moveToLogic.mount()
        const moving = logic.asyncActions.moveWorkflowToFolder(FIXTURE_WORKFLOWS[2].id)
        await waitFor(() => expect(lookups).toBe(1))
        logic.unmount()
        releaseLookup()
        await moving.catch(() => undefined)
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(moveToLogic.values.isOpen).toBe(false)
        expect(screen.queryByText("Couldn't find this workflow in project files")).not.toBeInTheDocument()
        expect(screen.queryByText("Couldn't load this workflow's folder")).not.toBeInTheDocument()
        logic.mount()
        unmountMoveTo()
    })

    it('closes the folders the person leaves, so only the open path shows as open', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectTreeFolder('Billing/Cards', false)
        expect(logic.values.expandedFolders).toEqual(
            expect.arrayContaining(['project://', 'project://Billing', 'project://Billing/Cards'])
        )
        logic.actions.selectTreeFolder('Empty', false)
        expect(logic.values.expandedFolders).toEqual(['project://', 'project://Empty'])
    })

    it('collapses the open folder when its tree row is selected again', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectTreeFolder('Billing', false)
        expect(logic.values.currentFolder).toBe('Billing')
        expect(logic.values.expandedFolders).toContain('project://Billing')
        logic.actions.selectTreeFolder('Billing', true)
        expect(logic.values.currentFolder).toBe('Billing')
        expect(logic.values.expandedFolders).not.toContain('project://Billing')
        logic.actions.selectTreeFolder('Billing', false)
        expect(logic.values.expandedFolders).toContain('project://Billing')
    })

    it('searches through subfolders while retaining the exact case-sensitive scope, without rebuilding the folder tree', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        const tree = logic.values.folderTree
        expect(tree[0].children?.map((item) => item.record?.path)).toContain('Billing')
        expect(logic.values.folderCounts.Billing).toBe(3)
        logic.actions.setValue({
            filters: [{ facet: 'in', value: 'Billing', negated: false }],
            text: FIXTURE_WORKFLOWS[1].name ?? '',
        })
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.childFolders).toEqual([])
        expect(workflowsListV2Logic.values.filteredRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.folderCounts.Billing).toBe(1)
        expect(logic.values.folderTree).toBe(tree)
        logic.actions.setValue({
            filters: [{ facet: 'in', value: 'billing', negated: false }],
            text: FIXTURE_WORKFLOWS[1].name ?? '',
        })
        expect(logic.values.folderRows).toEqual([])
    })

    it('replaces the open folder when a second folder pill is added', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setValue({
            filters: [
                { facet: 'in', value: 'Billing', negated: false },
                { facet: 'status', value: 'archived', negated: true },
                { facet: 'in', value: 'Billing/Cards', negated: false },
            ],
            text: '',
        })
        expect(workflowsListV2Logic.values.value.filters).toEqual([
            { facet: 'status', value: 'archived', negated: true },
            { facet: 'in', value: 'Billing/Cards', negated: false },
        ])
        expect(logic.values.currentFolder).toBe('Billing/Cards')
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
    })

    it('groups descendant matches by folder before sorting names', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setValue({
            filters: [
                { facet: 'in', value: 'Billing', negated: false },
                { facet: 'status', value: 'archived', negated: true },
            ],
            text: '',
        })
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id, FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.folderFileRows.map((row) => row.id)).toEqual([
            `workflow:${FIXTURE_WORKFLOWS[0].id}`,
            `workflow:${FIXTURE_WORKFLOWS[1].id}`,
            'email_template:template-receipt',
        ])
    })

    it('excludes a folder and its descendants with a negated scope pill', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setValue({
            filters: [
                { facet: 'in', value: 'Billing', negated: true },
                { facet: 'status', value: 'archived', negated: true },
            ],
            text: '',
        })
        expect(logic.values.folderRows.map((row) => row.id)).not.toContain(FIXTURE_WORKFLOWS[0].id)
        expect(logic.values.folderRows.map((row) => row.id)).not.toContain(FIXTURE_WORKFLOWS[1].id)
        expect(logic.values.folderTemplates).toEqual([])
    })

    it('moves a selected workflow and email template with the shared Move to dialog', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const unmountMoveTo = moveToLogic.mount()
        logic.actions.openFolder('Billing/Cards')
        logic.actions.toggleSelectedFile(`workflow:${FIXTURE_WORKFLOWS[1].id}`)
        logic.actions.toggleSelectedFile('email_template:template-receipt')
        logic.actions.moveSelectedFiles()
        expect(moveToLogic.values.movingItems.map((entry) => entry.ref)).toEqual([
            FIXTURE_WORKFLOWS[1].id,
            'template-receipt',
        ])
        unmountMoveTo()
    })

    it('offers email templates in the kind facet and scopes their matches', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const type = logic.values.folderFacets.find((facet) => facet.key === 'kind')!
        expect(logic.values.folderSearchItems.flatMap(type.getValues)).toContain('email-template')
        logic.actions.setValue({
            filters: [
                { facet: 'in', value: 'Billing', negated: false },
                { facet: 'kind', value: 'email-template', negated: false },
            ],
            text: '',
        })
        expect(logic.values.folderRows).toEqual([])
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toEqual(['template-receipt'])
    })

    it('drops both selected files through the existing move queue', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const paths: string[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/file_system/:id/move/': async ({ request, params }) => {
                    const body = (await request.json()) as { new_path: string }
                    paths.push(body.new_path)
                    return [
                        200,
                        {
                            id: params.id,
                            path: body.new_path,
                            type: params.id === 'nested' ? 'hog_flow' : 'message_template',
                            ref: params.id === 'nested' ? FIXTURE_WORKFLOWS[1].id : 'template-receipt',
                        },
                    ]
                },
            },
        })
        logic.actions.openFolder('Billing/Cards')
        logic.actions.toggleSelectedFile(`workflow:${FIXTURE_WORKFLOWS[1].id}`)
        logic.actions.toggleSelectedFile('email_template:template-receipt')
        await logic.asyncActions.dropFile('project/nested', 'project://Billing')
        await expectLogic(logic).toFinishAllListeners()
        await waitFor(() => expect(paths.sort()).toEqual(['Billing/Receipt', 'Billing/Renewal']))
    })
})

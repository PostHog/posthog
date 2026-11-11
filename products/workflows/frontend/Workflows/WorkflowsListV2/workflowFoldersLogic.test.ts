import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { folderNameError, workflowFoldersLogic } from './workflowFoldersLogic'
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

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [200, []],
                '/api/projects/:team_id/file_system/unfiled/': () => [200, { count: 0 }],
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('search')?.replace('type:', '')
                    const entries = [
                        { id: 'billing', path: 'Billing', type: 'folder' },
                        { id: 'cards', path: 'Billing/Cards', type: 'folder' },
                        { id: 'empty', path: 'Empty', type: 'folder' },
                        { id: 'dashboards', path: 'Reports', type: 'folder' },
                        {
                            id: 'report',
                            path: 'Reports/Overview',
                            type: 'insight',
                            ref: 'synthetic-report',
                            meta: { type: 'SQL' },
                        },
                        { id: 'unfiled', path: 'Unfiled', type: 'folder' },
                        { id: 'cohorts', path: 'Unfiled/Cohorts', type: 'folder' },
                        { id: 'direct', path: 'Billing/Welcome', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id },
                        { id: 'nested', path: 'Billing/Cards/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id },
                        {
                            id: 'receipt',
                            path: 'Billing/Cards/Receipt',
                            type: 'message_template',
                            ref: 'template-receipt',
                            team_id: MOCK_TEAM_ID,
                        },
                        {
                            id: 'sibling-receipt',
                            path: 'Billing/Cards/Staging receipt',
                            type: 'message_template',
                            ref: 'template-staging',
                            team_id: MOCK_TEAM_ID + 1,
                        },
                    ]
                    return [
                        200,
                        paginated(
                            entries.filter((entry) =>
                                type?.startsWith('-') ? entry.type === 'insight' : entry.type === type
                            )
                        ),
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

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
        await logic.asyncActions.loadBrowser()
        logic.actions.openFolder('Unfiled')
        expect(logic.values.folderTemplates.map((entry) => entry.ref)).toContain('synthetic-unfiled-email')
        expect(logic.values.folderPaths).toContain('Unfiled')
    })

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
        [
            'the reason the server gives',
            400,
            { detail: 'Path has too many levels.' },
            "Couldn't create the folder. Path has too many levels.",
        ],
        ['a retry when the server gives no reason', 500, {}, "Couldn't create the folder. Try again."],
    ])('reports a failed folder creation with %s and allows retry', async (_, status, body, message) => {
        await expectLogic(logic).toFinishAllListeners()
        const toast = jest.spyOn(lemonToast, 'error')
        useMocks({ post: { '/api/projects/:team_id/file_system/': () => [status, body] } })
        await logic.asyncActions.createFolder('Invoices', 'Billing')
        expect(logic.values.folderCreationError).toBeTruthy()
        expect(toast).toHaveBeenCalledWith(message)
        expect(logic.values.creatingFolder).toBe(false)
        toast.mockRestore()
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
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        useMocks({
            delete: {
                '/api/projects/:team_id/file_system/empty/': ({ request }) => {
                    recursive = new URL(request.url).searchParams.get('recursive')
                    return [status, body]
                },
            },
        })
        try {
            await expectLogic(logic).toFinishAllListeners()
            await logic.asyncActions.deleteFolder('Empty')
            expect(recursive).toBe('false')
            expect(logic.values.folderPaths.includes('Empty')).toBe(status !== 204)
            expect(errorToast.mock.calls.map(([message]) => message)).toEqual(toast)
        } finally {
            errorToast.mockRestore()
        }
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
        ['pages through a folder the shared tree cut to its first page, and nothing else', 200],
        ['keeps the cached files of a cut folder whose next page fails', 500],
    ])('%s', async (_name, nextPageStatus) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        const requests: URLSearchParams[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    return [
                        nextPageStatus,
                        paginated(
                            params.get('parent') === 'Billing'
                                ? [
                                      {
                                          id: 'direct',
                                          path: 'Billing/Welcome',
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
        projectTreeDataLogic.actions.loadFolderSuccess(
            'Billing',
            [{ id: 'cards', path: 'Billing/Cards', type: 'folder' }],
            true,
            1,
            true
        )
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.map((params) => params.get('parent'))).toEqual(['Billing'])
        expect(logic.values.browserReadyLoading).toBe(false)
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
        expect(logic.values.filesByRef[`hog_flow::${FIXTURE_WORKFLOWS[0].id}`]).toBeUndefined()
        expect(logic.values.filesByRef[`hog_flow::${FIXTURE_WORKFLOWS[1].id}`]?.path).toEqual('Billing/Cards/Renewal')
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

    it("moves workflow files and drops folders and other products' files to match a full reload", async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderPaths).not.toContain('Reports')
        useMocks({
            get: {
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

    it("keeps the metadata of other products' files it writes into the shared tree", async () => {
        await expectLogic(logic).toFinishAllListeners()
        const report = projectTreeDataLogic.values.folders['Reports']?.find((entry) => entry.id === 'report')
        expect(report?.meta).toEqual({ type: 'SQL' })
    })

    it("paints the folders before other products' files load, and checks folder names once they have", async () => {
        logic.unmount()
        let releaseOtherFiles!: () => void
        const otherFilesHeld = new Promise<void>((resolve) => (releaseOtherFiles = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search') ?? ''
                    if (search.startsWith('-')) {
                        await otherFilesHeld
                        return [200, paginated([{ id: 'dashboards', path: 'Reports', type: 'folder' }])]
                    }
                    return [
                        200,
                        paginated(search === 'type:folder' ? [{ id: 'billing', path: 'Billing', type: 'folder' }] : []),
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        logic = workflowFoldersLogic()
        logic.mount()

        await waitFor(() => expect(logic.values.browserReady).toBe(true))
        expect(logic.values.folderPaths).toContain('Billing')
        logic.actions.startFolderDraft('')
        logic.actions.setFolderDraftName('reports')
        expect(logic.values.folderDraftError).toBe('Checking existing folder names. Try again in a moment.')

        releaseOtherFiles()
        await waitFor(() => expect(logic.values.folderDraftError).toBe(EXISTS))
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

        await waitFor(() => expect(logic.values.otherFilesReady).toBe(true))
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

    it.each([
        ['every scan fails', false, true],
        ["only the other products' scan fails, before the folder scans answer", true, false],
    ])('reports a failed scan when %s, and recovers on retry', async (_, folderScansSucceed, blocksContents) => {
        await expectLogic(logic).toFinishAllListeners()
        let releaseFolderScans!: () => void
        const folderScansHeld = new Promise<void>((resolve) => (releaseFolderScans = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    if ((new URL(request.url).searchParams.get('search') ?? '').startsWith('-')) {
                        return [500, { detail: 'Unavailable' }]
                    }
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
        useMocks({ get: { '/api/projects/:team_id/file_system/': () => [200, paginated([])] } })
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

    it('reveals the scoped folder and its subfolders when opened from a link', async () => {
        logic.unmount()
        workflowsListV2Logic.mount()
        workflowsListV2Logic.actions.setValue({
            filters: [{ facet: 'in', value: 'Billing', negated: false }],
            text: '',
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.expandedFolders).toContain('project://Billing')
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

    it('searches through subfolders while retaining the exact case-sensitive scope', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openFolder('Billing')
        logic.actions.setValue({
            filters: [{ facet: 'in', value: 'Billing', negated: false }],
            text: FIXTURE_WORKFLOWS[1].name ?? '',
        })
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
        expect(logic.values.childFolders).toEqual([])
        expect(workflowsListV2Logic.values.filteredRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[1].id])
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

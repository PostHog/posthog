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

import { workflowFoldersLogic } from './workflowFoldersLogic'
import { FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'
import { workflowsListV2Logic } from './workflowsListV2Logic'

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
                        { id: 'report', path: 'Reports/Overview', type: 'dashboard', ref: 'synthetic-report' },
                        { id: 'unfiled', path: 'Unfiled', type: 'folder' },
                        { id: 'cohorts', path: 'Unfiled/Cohorts', type: 'folder' },
                        { id: 'direct', path: 'Billing/Welcome', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[0].id },
                        { id: 'nested', path: 'Billing/Cards/Renewal', type: 'hog_flow', ref: FIXTURE_WORKFLOWS[1].id },
                        {
                            id: 'receipt',
                            path: 'Billing/Cards/Receipt',
                            type: 'message_template',
                            ref: 'template-receipt',
                        },
                    ]
                    return [
                        200,
                        paginated(
                            entries.filter((entry) =>
                                type?.startsWith('-') ? entry.type === 'dashboard' : entry.type === type
                            )
                        ),
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_PROJECT_FILES]: true })
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

    it('shows email templates in their open folder and includes them in folder counts', async () => {
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

    it('reports a failed folder creation and allows retry', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const toast = jest.spyOn(lemonToast, 'error')
        useMocks({ post: { '/api/projects/:team_id/file_system/': () => [500, { detail: 'Unavailable' }] } })
        await logic.asyncActions.createFolder('Invoices', 'Billing')
        expect(logic.values.folderCreationError).toBeTruthy()
        expect(toast).toHaveBeenCalledWith("Couldn't create the folder")
        expect(logic.values.creatingFolder).toBe(false)
        toast.mockRestore()
    })

    it('deletes only an empty project folder without deleting its contents', async () => {
        let recursive: string | null | undefined
        useMocks({
            delete: {
                '/api/projects/:team_id/file_system/empty/': ({ request }) => {
                    recursive = new URL(request.url).searchParams.get('recursive')
                    return [204, null]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        await logic.asyncActions.deleteFolder('Empty')
        expect(recursive).toBe('false')
        expect(logic.values.folderPaths).not.toContain('Empty')
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
        projectTreeDataLogic.actions.pruneClosedFolders(['project://'])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.folderCounts.Billing).toBe(3)
        expect(logic.values.folderRows.map((row) => row.id)).toEqual([FIXTURE_WORKFLOWS[0].id])
    })

    it('reports a failed folder index and recovers on retry', async () => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:team_id/file_system/': () => [500, { detail: 'Unavailable' }] } })
        await expectLogic(logic, () => logic.actions.loadBrowser()).toFinishAllListeners()
        expect(logic.values.browserLoadFailed).toBe(true)
        useMocks({ get: { '/api/projects/:team_id/file_system/': () => [200, paginated([])] } })
        await expectLogic(logic, () => logic.actions.loadBrowser()).toFinishAllListeners()
        expect(logic.values.browserLoadFailed).toBe(false)
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

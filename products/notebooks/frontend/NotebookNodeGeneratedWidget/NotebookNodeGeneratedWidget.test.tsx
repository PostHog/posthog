import { render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { MarkdownNotebookV2 } from 'scenes/notebooks/Notebook/MarkdownNotebookV2Renderer'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { notebooksWidgetStatus, notebooksWidgetVersions } from 'products/notebooks/frontend/generated/api'

jest.mock('scenes/notebooks/Notebook/migrations/migrate', () => {
    const actual = jest.requireActual('scenes/notebooks/Notebook/migrations/migrate')
    return { ...actual, migrate: jest.fn(async (notebook: unknown) => notebook) }
})

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksWidgetCancel: jest.fn(),
    notebooksWidgetFrame: jest.fn(),
    notebooksWidgetGenerate: jest.fn(),
    notebooksWidgetRevert: jest.fn(),
    notebooksWidgetSaveSource: jest.fn(),
    notebooksWidgetSource: jest.fn(),
    notebooksWidgetStatus: jest.fn(),
    notebooksWidgetVersions: jest.fn(),
    notebooksSqlV2StateRetrieve: jest.fn(),
}))

const SHORT_ID = 'generated-widget-progress'
const MARKDOWN =
    '<GeneratedWidget showFilters showResults nodeId="globe" prompt="Render a globe" model="claude-sonnet-4-6" />'
const cachedNotebook = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Generated widget progress',
    content: buildMarkdownNotebookContent(MARKDOWN),
    text_content: MARKDOWN,
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2026-08-27T12:00:00Z',
    created_by: null,
    last_modified_at: '2026-08-27T12:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('NotebookNodeGeneratedWidget', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as never)
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'generating',
            error_detail: null,
            artifact_url: null,
            frame_names: [],
            current_version_id: '00000000-0000-0000-0000-000000000002',
            widget_id: '00000000-0000-0000-0000-000000000003',
            instance_id: '00000000-0000-0000-0000-000000000004',
            has_versions: true,
            active_job: {
                id: '00000000-0000-0000-0000-000000000001',
                status: 'generating',
                phase: 'generating_source',
                model: 'claude-sonnet-4-6',
                created_at: '2026-08-27T12:00:00Z',
                started_at: '2026-08-27T12:00:00Z',
            },
        })
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({ results: [], count: 0, next_offset: null })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('shows generation progress only in filters when filters and results are open', async () => {
        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        await waitFor(() => expect(screen.getAllByText('Regenerating widget…')).toHaveLength(1))
    })
})

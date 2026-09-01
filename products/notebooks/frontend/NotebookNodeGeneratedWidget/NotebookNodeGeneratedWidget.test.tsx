import { MOCK_TEAM_ID } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { MarkdownNotebookV2 } from 'scenes/notebooks/Notebook/MarkdownNotebookV2Renderer'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import {
    notebooksWidgetSource,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
} from 'products/notebooks/frontend/generated/api'

jest.mock('scenes/notebooks/Notebook/migrations/migrate', () => {
    const actual = jest.requireActual('scenes/notebooks/Notebook/migrations/migrate')
    return { ...actual, migrate: jest.fn(async (notebook: unknown) => notebook) }
})

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksWidgetCancel: jest.fn(),
    notebooksWidgetFrame: jest.fn(),
    notebooksWidgetGenerate: jest.fn(),
    notebooksWidgetRevert: jest.fn(),
    notebooksWidgetSource: jest.fn(),
    notebooksWidgetStatus: jest.fn(),
    notebooksWidgetVersions: jest.fn(),
}))

const SHORT_ID = 'generated-widget-progress'
const MARKDOWN = '<Widget showFilters showResults nodeId="globe" prompt="Render a globe" model="claude-sonnet-4-6" />'
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
            security_review: null,
            build_hash: null,
        })
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({ results: [], count: 0, next_offset: null })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)
    })

    afterEach(() => {
        cleanup()
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

        expect(screen.getByText('Widget')).toBeTruthy()
        await waitFor(() => expect(screen.getAllByText('Regenerating widget…')).toHaveLength(1))
    })

    it('opens the current source with an improvement prompt', async () => {
        const versionId = '00000000-0000-0000-0000-000000000002'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'ready',
            error_detail: null,
            artifact_url: 'https://example.com/widget.html',
            frame_names: [],
            current_version_id: versionId,
            widget_id: '00000000-0000-0000-0000-000000000003',
            instance_id: '00000000-0000-0000-0000-000000000004',
            has_versions: true,
            active_job: null,
            security_review: null,
            build_hash: 'a'.repeat(64),
        })
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [
                {
                    id: versionId,
                    parent_version_id: null,
                    version: 1,
                    version_operation: 'initial',
                    prompt_delta: 'Render a globe',
                    effective_prompt: 'Render a globe',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-27T12:00:00Z',
                    build_status: 'ready',
                    artifact_url: 'https://example.com/widget.html',
                    frame_names: [],
                    is_current: true,
                    security_review: null,
                    build_hash: 'a'.repeat(64),
                },
            ],
            count: 1,
            next_offset: null,
        })
        jest.mocked(notebooksWidgetSource).mockResolvedValue({
            source: 'export default function Widget() {}',
        })
        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        const improveButton = await screen.findByText('Improve…')
        const actionContainer = improveButton.closest('button')!.parentElement!
        const actionButtons = [
            improveButton,
            within(actionContainer).getByText('Regenerate…'),
            within(actionContainer).getByText('View source'),
            within(actionContainer).getByText('Reload preview'),
        ]
        actionButtons.slice(0, -1).forEach((button, index) => {
            expect(
                button.compareDocumentPosition(actionButtons[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING
            ).toBeTruthy()
        })
        jest.mocked(notebooksWidgetStatus).mockClear()
        fireEvent.click(actionButtons[3])
        await waitFor(() => expect(notebooksWidgetStatus).toHaveBeenCalledWith(String(MOCK_TEAM_ID), SHORT_ID, 'globe'))

        fireEvent.click(actionButtons[2])

        await waitFor(() =>
            expect(notebooksWidgetSource).toHaveBeenCalledWith(String(MOCK_TEAM_ID), SHORT_ID, 'globe', {
                version_id: versionId,
            })
        )
        expect(screen.getByText('Widget source')).toBeTruthy()
        expect(screen.getByText('What would you like to change?')).toBeTruthy()
        expect(screen.getByText('Build changes')).toBeTruthy()
    })

    it('shows security findings before mounting the exact build', async () => {
        const versionId = '00000000-0000-0000-0000-000000000005'
        const buildHash = 'b'.repeat(64)
        const securityReview = {
            severity: 'high' as const,
            summary: 'The widget may send notebook data to another window.',
            findings: [
                {
                    severity: 'high' as const,
                    title: 'Notebook data may leave the preview',
                    details: 'The source sends rows to the parent window without using the approved bridge.',
                },
            ],
            model: 'claude-haiku-4-5',
            review_version: '1',
            reviewed_at: '2026-08-31T10:00:00Z',
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'ready',
            error_detail: null,
            artifact_url: 'https://example.com/untrusted-widget.html',
            frame_names: [],
            current_version_id: versionId,
            widget_id: '00000000-0000-0000-0000-000000000006',
            instance_id: '00000000-0000-0000-0000-000000000007',
            has_versions: true,
            active_job: null,
            security_review: securityReview,
            build_hash: buildHash,
        })
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [
                {
                    id: versionId,
                    parent_version_id: null,
                    version: 1,
                    version_operation: 'initial',
                    prompt_delta: 'Render a globe',
                    effective_prompt: 'Render a globe',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-27T12:00:00Z',
                    build_status: 'ready',
                    artifact_url: 'https://example.com/untrusted-widget.html',
                    frame_names: [],
                    is_current: true,
                    security_review: securityReview,
                    build_hash: buildHash,
                },
            ],
            count: 1,
            next_offset: null,
        })
        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }

        const { container } = render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        await screen.findByText('Security review found potential issues')
        expect(screen.getByText('Notebook data may leave the preview')).toBeTruthy()
        expect(screen.getByText('Run widget anyway')).toBeTruthy()
        await waitFor(() => expect(container.querySelector('[data-attr="notebook-widget-run"]')).not.toBeNull())
        const runButton = container.querySelector('[data-attr="notebook-widget-run"]')!
        expect(container.querySelector('iframe')).toBeNull()

        fireEvent.click(runButton)

        await waitFor(() => expect(container.querySelector('[data-attr="notebook-widget-run"]')).toBeNull())
        await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe(
            'https://example.com/untrusted-widget.html#theme=light'
        )
    })

    it('mounts a widget automatically when the security review passes', async () => {
        const versionId = '00000000-0000-0000-0000-000000000008'
        const buildHash = 'c'.repeat(64)
        const securityReview = {
            severity: 'none' as const,
            summary: 'No security issues found.',
            findings: [],
            model: 'claude-haiku-4-5',
            review_version: '1',
            reviewed_at: '2026-08-31T10:00:00Z',
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'ready',
            error_detail: null,
            artifact_url: 'https://example.com/reviewed-widget.html',
            frame_names: [],
            current_version_id: versionId,
            widget_id: '00000000-0000-0000-0000-000000000009',
            instance_id: '00000000-0000-0000-0000-000000000010',
            has_versions: true,
            active_job: null,
            security_review: securityReview,
            build_hash: buildHash,
        })
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [
                {
                    id: versionId,
                    parent_version_id: null,
                    version: 1,
                    version_operation: 'initial',
                    prompt_delta: 'Render a globe',
                    effective_prompt: 'Render a globe',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-31T10:00:00Z',
                    build_status: 'ready',
                    artifact_url: 'https://example.com/reviewed-widget.html',
                    frame_names: [],
                    is_current: true,
                    security_review: securityReview,
                    build_hash: buildHash,
                },
            ],
            count: 1,
            next_offset: null,
        })
        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }

        const { container } = render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())
        expect(container.querySelector('[data-attr="notebook-widget-run"]')).toBeNull()
        expect(screen.getByText('Security review: No issues found')).toBeTruthy()
    })
})

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
    notebooksWidgetCancel,
    notebooksWidgetSource,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
} from 'products/notebooks/frontend/generated/api'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { NotebookWidgetGenerationModal } from './NotebookWidgetGenerationModal'

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

jest.mock('react-intersection-observer', () => ({
    useInView: () => ({ ref: () => undefined, inView: true }),
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
const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook' }

describe('NotebookNodeGeneratedWidget', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as never)
        jest.spyOn(api.notebooks, 'get').mockResolvedValue(cachedNotebook)
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

        logic = notebookLogic(logicProps)
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
        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        expect(screen.getByText('Widget')).toBeTruthy()
        await waitFor(() => expect(screen.getAllByText('Regenerating widget…')).toHaveLength(1))
    })

    it('renders without crashing when the markdown tag has a non-string prompt or unknown model', async () => {
        logic.unmount()
        const notebookWithMalformedTag = {
            ...cachedNotebook,
            // A valueless `prompt` attribute parses to boolean true, and the model is an unsupported string.
            content: buildMarkdownNotebookContent(
                '<Widget showResults nodeId="globe" prompt model="not-a-real-model" />'
            ),
        }
        jest.mocked(api.notebooks.get).mockResolvedValue(notebookWithMalformedTag)
        logic = notebookLogic(logicProps)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        expect(await screen.findByText('Regenerating widget…')).toBeTruthy()
    })

    it('does not offer initial generation in the settings panel while status is still loading', async () => {
        // The status request never resolves, so `status` stays null through the render.
        jest.mocked(notebooksWidgetStatus).mockImplementation(() => new Promise(() => {}))

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        expect(await screen.findByText('Widget')).toBeTruthy()
        // Before the first status response the panel must not present the initial form, or an
        // editor could start a job that the backend turns into a regeneration.
        expect(screen.queryByText('Generate widget')).toBeNull()
        expect(screen.queryByText('Instructions')).toBeNull()
    })

    it('shows cancellation errors while initial generation is still running', async () => {
        jest.mocked(notebooksWidgetCancel).mockRejectedValue(new Error('Cancel request failed'))

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        fireEvent.click(await screen.findByText('Cancel'))

        expect(await screen.findByText('Cancel request failed')).toBeTruthy()
    })

    it('shows a generation failure inside the generation modal', async () => {
        const generationModalLogicProps = {
            projectId: MOCK_TEAM_ID,
            notebookShortId: SHORT_ID,
            nodeId: 'globe',
            prompt: 'Render a globe',
            model: 'claude-sonnet-4-6' as const,
            isEditable: true,
            persistNotebook: async (): Promise<void> => undefined,
            getContent: () => null,
        }
        const widgetLogic = notebookNodeGeneratedWidgetLogic(generationModalLogicProps)
        widgetLogic.mount()
        await expectLogic(widgetLogic).toFinishAllListeners()
        widgetLogic.actions.openGenerationModal('improve')
        widgetLogic.actions.generationFailed('The widget could not be generated.')

        render(<NotebookWidgetGenerationModal logicProps={generationModalLogicProps} />)

        // A failed generation keeps the modal open, so the reason must be visible inside it.
        expect(await screen.findByText('The widget could not be generated.')).toBeTruthy()
        widgetLogic.unmount()
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
        await waitFor(() =>
            expect(notebooksWidgetStatus).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                SHORT_ID,
                'globe',
                expect.objectContaining({ signal: expect.anything() })
            )
        )

        fireEvent.click(actionButtons[2])

        await waitFor(() =>
            expect(notebooksWidgetSource).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                SHORT_ID,
                'globe',
                { version_id: versionId },
                expect.objectContaining({ signal: expect.anything() })
            )
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
        expect(container.querySelector('iframe')?.getAttribute('title')).toBe('Widget')
    })

    it('requires exact-build consent when the security review passes', async () => {
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
        const { container } = render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        await screen.findByText('Review this widget before running it')
        expect(container.querySelector('iframe')).toBeNull()
        expect(screen.getByText('Automated review: No potential issues flagged')).toBeTruthy()

        fireEvent.click(container.querySelector('[data-attr="notebook-widget-run"]')!)

        await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())
        expect(container.querySelector('[data-attr="notebook-widget-run"]')).toBeNull()
    })

    it('opens regeneration from a failed preview when the filters are closed', async () => {
        const versionId = '00000000-0000-0000-0000-000000000011'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'failed',
            error_detail: 'The widget build failed.',
            artifact_url: null,
            frame_names: [],
            current_version_id: versionId,
            widget_id: '00000000-0000-0000-0000-000000000012',
            instance_id: '00000000-0000-0000-0000-000000000013',
            has_versions: true,
            active_job: null,
            security_review: null,
            build_hash: null,
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
                    build_status: 'failed',
                    artifact_url: null,
                    frame_names: [],
                    is_current: true,
                    security_review: null,
                    build_hash: null,
                },
            ],
            count: 1,
            next_offset: null,
        })
        logic.unmount()
        const notebookWithoutFilters = {
            ...cachedNotebook,
            content: buildMarkdownNotebookContent(
                '<Widget showResults nodeId="globe" prompt="Render a globe" model="claude-sonnet-4-6" />'
            ),
        }
        jest.mocked(api.notebooks.get).mockResolvedValue(notebookWithoutFilters)
        logic = notebookLogic(logicProps)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        fireEvent.click(await screen.findByText('Regenerate…'))

        expect(await screen.findByText('Regenerate widget')).toBeTruthy()
        expect(screen.getByDisplayValue('Render a globe')).toBeTruthy()
    })

    it('keeps source available when the selected version has no preview', async () => {
        const versionId = '00000000-0000-0000-0000-000000000014'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue({
            lifecycle_status: 'ready',
            error_detail: null,
            artifact_url: null,
            frame_names: [],
            current_version_id: versionId,
            widget_id: '00000000-0000-0000-0000-000000000015',
            instance_id: '00000000-0000-0000-0000-000000000016',
            has_versions: true,
            active_job: null,
            security_review: null,
            build_hash: null,
        })
        jest.mocked(notebooksWidgetSource).mockResolvedValue({
            source: 'export default function Widget() {}',
        })
        logic.unmount()
        const notebookWithoutFilters = {
            ...cachedNotebook,
            content: buildMarkdownNotebookContent(
                '<Widget showResults nodeId="globe" prompt="Render a globe" model="claude-sonnet-4-6" />'
            ),
        }
        jest.mocked(api.notebooks.get).mockResolvedValue(notebookWithoutFilters)
        logic = notebookLogic(logicProps)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)

        render(
            <BindLogic logic={notebookLogic} props={logicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        expect(await screen.findByText(/preview is no longer available/)).toBeTruthy()
        fireEvent.click(screen.getByText('View source'))

        await waitFor(() =>
            expect(notebooksWidgetSource).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                SHORT_ID,
                'globe',
                { version_id: versionId },
                expect.objectContaining({ signal: expect.anything() })
            )
        )
        expect(screen.getByText('Widget source')).toBeTruthy()
    })

    it('does not load generated widgets in publicly shared notebooks', async () => {
        logic.unmount()
        jest.mocked(notebooksWidgetStatus).mockClear()
        const sharedLogicProps: NotebookLogicProps = { ...logicProps, cachedNotebook }
        logic = notebookLogic(sharedLogicProps)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        const statusCallCount = jest.mocked(notebooksWidgetStatus).mock.calls.length

        render(
            <BindLogic logic={notebookLogic} props={sharedLogicProps}>
                <MarkdownNotebookV2 />
            </BindLogic>
        )

        expect(await screen.findByText('Node cannot be rendered')).toBeTruthy()
        expect(notebooksWidgetStatus).toHaveBeenCalledTimes(statusCallCount)
    })
})

import { act, cleanup, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { foregroundStreamLogic, toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { NotebookAppAgentIntegration } from './NotebookAppAgentIntegration'
import { emptyAppLayout } from './notebookAppLayout'
import { notebookAppLogic } from './notebookAppLogic'

const shortId = 'app-test'

describe('app builder AI updates', () => {
    let logic: ReturnType<typeof notebookAppLogic.build>
    let saved = {
        ...notebookTestTemplate('Test notebook', []),
        short_id: shortId,
        content: buildMarkdownNotebookContent('A notebook'),
        app_revision: 1,
        app_draft: { ...emptyAppLayout(), title: 'Original app' },
    }

    beforeEach(() => {
        initKeaTests()
        saved = {
            ...saved,
            content: buildMarkdownNotebookContent('A notebook'),
            app_revision: 1,
            app_draft: { ...emptyAppLayout(), title: 'Original app' },
        }
        useMocks({
            get: {
                '/api/projects/:team_id/notebooks/app-test': () => [200, saved],
                '/api/projects/:team_id/notebooks/app-test/collab/stream': () => [503, {}],
            },
        })
        logic = notebookAppLogic({ shortId })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each(['notebook', 'source', 'app', 'another-notebook'])(
        'keeps unsaved edits when canceling navigation to %s',
        async (target) => {
            await waitFor(() => expect(logic.values.layout.title).toBe('Original app'))
            router.actions.replace(urls.notebook(shortId), { view: 'builder' })
            const builderPath = router.values.location.pathname
            logic.actions.changeLayout({ ...logic.values.layout, title: 'Unsaved app' })
            jest.spyOn(window, 'confirm').mockReturnValue(false)
            const pathname = target === 'another-notebook' ? builderPath.replace(shortId, 'other') : builderPath
            router.actions.push(
                pathname,
                target === 'app' ? { view: 'app' } : {},
                target === 'source' ? { node: 'cell-1' } : {}
            )
            expect(router.values.location.pathname).toBe(builderPath)
            expect(router.values.searchParams.view).toBe('builder')
            expect(logic.values.layout.title).toBe('Unsaved app')
            jest.spyOn(window, 'confirm').mockReturnValue(true)
            router.actions.push(pathname, target === 'app' ? { view: 'app' } : {})
            expect(router.values.location.pathname).toBe(
                target === 'another-notebook' ? builderPath.replace(shortId, 'other') : builderPath
            )
            expect(router.values.searchParams.view).toBe(target === 'app' ? 'app' : undefined)
        }
    )

    it.each([
        { tool: 'notebooks-add-cell', input: { notebook_id: shortId }, expected: 'AI source' },
        { tool: 'notebooks-run', input: { notebook_id: shortId }, followUp: true, expected: 'AI source' },
        { tool: 'notebooks-widget-status', input: { short_id: shortId }, expected: 'AI source' },
        { tool: 'notebooks-run', input: { notebook_id: 'another-notebook' }, expected: 'A notebook' },
    ])('refreshes source after a foreground turn: $tool $input', async ({ tool, input, followUp, expected }) => {
        const source = notebookLogic({ shortId })
        source.actions.loadNotebook()
        await waitFor(() => expect(source.values.markdownEditorValue).toBe('A notebook'))
        render(<NotebookAppAgentIntegration shortId={shortId} />)
        act(() => {
            foregroundStreamLogic.actions.setForegroundStream('source-run', 'test')
            toolStreamEventsLogic.actions.claimApplyBackTargets('source-run')
            logic.actions.changeLayout({ ...logic.values.layout, title: 'My unsaved app' })
        })
        saved = { ...saved, content: buildMarkdownNotebookContent('AI source') }
        await act(async () => {
            const completion = {
                streamKey: 'source-run',
                toolCallId: 'source-update',
                toolName: tool,
                rawToolName: 'exec',
                phase: 'completed',
                source: 'live',
                invocation: {
                    toolCallId: 'source-update',
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    input: { command: `call ${tool} ${JSON.stringify(input)}` },
                    status: 'completed',
                    contentBlocks: [],
                },
            } satisfies ToolStreamEvent
            toolStreamEventsLogic.actions.emitToolEvent(completion)
            if (followUp) {
                toolStreamEventsLogic.actions.emitToolEvent({
                    ...completion,
                    toolName: 'notebooks-widget-status',
                    toolCallId: 'other-widget',
                    invocation: {
                        ...completion.invocation,
                        toolCallId: 'other-widget',
                        input: { command: 'call notebooks-widget-status {"short_id":"another-notebook"}' },
                    },
                })
            }
            expect(source.values.markdownEditorValue).toBe('A notebook')
            toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: 'source-run' })
            await expectLogic(source).toFinishAllListeners()
        })
        expect(source.values.markdownEditorValue).toBe(expected)
        expect(logic.values.layout.title).toBe('My unsaved app')
    })

    it.each([
        { target: shortId, dirty: false, expected: 'AI app', pending: false },
        { target: shortId, dirty: true, expected: 'My unsaved app', pending: true },
        { target: 'another-notebook', dirty: false, expected: 'Original app', pending: false },
    ])('applies updates without replacing other work: %j', async ({ target, dirty, expected, pending }) => {
        await waitFor(() => expect(logic.values.layout.title).toBe('Original app'))
        render(<NotebookAppAgentIntegration shortId={shortId} />)
        act(() => {
            foregroundStreamLogic.actions.setForegroundStream('app-run', 'test')
            toolStreamEventsLogic.actions.claimApplyBackTargets('app-run')
            if (dirty) {
                logic.actions.changeLayout({ ...logic.values.layout, title: 'My unsaved app' })
            }
        })
        saved = { ...saved, app_revision: 2, app_draft: { ...saved.app_draft, title: 'AI app' } }
        await act(async () => {
            toolStreamEventsLogic.actions.emitToolEvent({
                streamKey: 'app-run',
                toolCallId: 'app-update',
                toolName: 'notebooks-app-update',
                rawToolName: 'exec',
                phase: 'completed',
                source: 'live',
                invocation: {
                    toolCallId: 'app-update',
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    input: { command: `call notebooks-app-update ${JSON.stringify({ short_id: target })}` },
                    status: 'completed',
                    contentBlocks: [],
                },
            } satisfies ToolStreamEvent)
            await expectLogic(logic).toFinishAllListeners()
        })
        expect(logic.values.layout.title).toBe(expected)
        expect(logic.values.agentUpdatePending).toBe(pending)
        expect(logic.values.savedNotebook?.app_revision).toBe(target === shortId && !dirty ? 2 : 1)
    })
})

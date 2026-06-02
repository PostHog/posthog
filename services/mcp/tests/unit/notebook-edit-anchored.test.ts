import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Schemas } from '@/api/generated'
import { PostHogApiError } from '@/lib/errors'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import editNotebook from '@/tools/notebooks/editByReplacement'
import type { WithPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn(),
}))

const mockIsFeatureFlagEnabled = vi.mocked(isFeatureFlagEnabled)

type ProseMirrorTestNode = { type: string } & Record<string, unknown>

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://app.posthog.com/project/${projectId}`,
        } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
            getAnalyticsContext: vi.fn().mockResolvedValue({ organizationId: 'org1', projectUuid: 'proj1' }),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function paragraph(text: string): ProseMirrorTestNode {
    return { type: 'paragraph', content: [{ type: 'text', text }] }
}

function emptyParagraph(): ProseMirrorTestNode {
    return { type: 'paragraph' }
}

function heading(text: string): ProseMirrorTestNode {
    return { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text }] }
}

function headingWithLevel(level: number, text: string): ProseMirrorTestNode {
    return { type: 'heading', attrs: { level }, content: [{ type: 'text', text }] }
}

function bulletList(...items: string[]): ProseMirrorTestNode {
    return { type: 'bulletList', content: items.map((item) => ({ type: 'listItem', content: [paragraph(item)] })) }
}

function codeBlock(text: string): ProseMirrorTestNode {
    return { type: 'codeBlock', content: [{ type: 'text', text }] }
}

function hogqlNode(code: string, returnVariable: string = 'hogql_df', title?: string): ProseMirrorTestNode {
    return {
        type: 'ph-hogql-sql',
        attrs: {
            code,
            returnVariable,
            ...(title ? { title } : {}),
            __init: { showSettings: true },
        },
    }
}

function pythonNode(code: string, title?: string): ProseMirrorTestNode {
    return {
        type: 'ph-python',
        attrs: {
            code,
            ...(title ? { title } : {}),
            __init: { showSettings: true },
        },
    }
}

function queryNode(query: Record<string, unknown>, title?: string): ProseMirrorTestNode {
    return {
        type: 'ph-query',
        attrs: {
            query,
            ...(title ? { title } : {}),
        },
    }
}

function doc(...content: ProseMirrorTestNode[]): Record<string, unknown> {
    return { type: 'doc', content }
}

function bodyForCall(requestMock: ReturnType<typeof vi.fn>, callIndex: number): Record<string, unknown> {
    const call = requestMock.mock.calls[callIndex]
    if (!call) {
        throw new Error(`Missing request call ${callIndex}`)
    }
    return call[0].body as Record<string, unknown>
}

describe('notebook-edit anchored edits', () => {
    beforeEach(() => {
        mockIsFeatureFlagEnabled.mockResolvedValue(true)
    })

    it('appends nodes through the notebook collab save endpoint', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Hello')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 4,
                title: 'Notebook',
                content: doc(paragraph('Hello'), paragraph('Added')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        const result = (await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [{ type: 'append', nodes: [paragraph('Added')] }],
        })) as WithPostHogUrl<Schemas.Notebook & { applied_edits: number }>

        expect(result._posthogUrl).toBe('https://app.posthog.com/project/42/notebooks/abc123')
        expect(result.applied_edits).toBe(1)
        expect(requestMock).toHaveBeenNthCalledWith(1, {
            method: 'GET',
            path: '/api/projects/42/notebooks/abc123/',
        })
        expect(requestMock).toHaveBeenNthCalledWith(2, {
            method: 'POST',
            path: '/api/projects/42/notebooks/abc123/collab/save/',
            body: expect.any(Object),
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 3,
            text_content: 'Hello\nAdded',
            content: doc(paragraph('Hello'), paragraph('Added')),
            steps: [
                {
                    stepType: 'replace',
                    from: 7,
                    to: 7,
                    slice: { content: [paragraph('Added')] },
                },
            ],
        })
        expect(body.client_id).toEqual(expect.stringMatching(/^mcp-/))
    })

    it('turns simple Markdown content into notebook blocks', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Intro')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 4,
                title: 'Notebook',
                content: doc(
                    paragraph('Intro'),
                    headingWithLevel(1, 'Added section'),
                    bulletList('First item', 'Second item'),
                    codeBlock('select 1')
                ),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'append',
                    content: '# Added section\n\n- First item\n- Second item\n\n```sql\nselect 1\n```',
                    content_format: 'markdown',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 3,
            text_content: 'Intro\nAdded section\nFirst item\nSecond item\nselect 1',
            content: doc(
                paragraph('Intro'),
                headingWithLevel(1, 'Added section'),
                bulletList('First item', 'Second item'),
                codeBlock('select 1')
            ),
            steps: [
                {
                    stepType: 'replace',
                    from: 7,
                    to: 7,
                    slice: {
                        content: [
                            headingWithLevel(1, 'Added section'),
                            bulletList('First item', 'Second item'),
                            codeBlock('select 1'),
                        ],
                    },
                },
            ],
        })
    })

    it('turns analysis Markdown blocks into executable notebook nodes', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Intro')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 4,
                title: 'Notebook',
                content: doc(
                    paragraph('Intro'),
                    hogqlNode('SELECT event, count() FROM events GROUP BY event', 'events_df', 'Recent events'),
                    pythonNode('print(events_df.head())', 'Summarize')
                ),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'append',
                    content:
                        '<hogql title="Recent events" return_variable="events_df">\nSELECT event, count() FROM events GROUP BY event\n</hogql>\n\n<python title="Summarize">\nprint(events_df.head())\n</python>',
                    content_format: 'markdown',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 3,
            text_content:
                'Intro\n<hogql title="Recent events" return_variable="events_df">\nSELECT event, count() FROM events GROUP BY event\n</hogql>\n<python title="Summarize">\nprint(events_df.head())\n</python>',
            content: doc(
                paragraph('Intro'),
                hogqlNode('SELECT event, count() FROM events GROUP BY event', 'events_df', 'Recent events'),
                pythonNode('print(events_df.head())', 'Summarize')
            ),
            steps: [
                {
                    stepType: 'replace',
                    from: 7,
                    to: 7,
                    slice: {
                        content: [
                            hogqlNode('SELECT event, count() FROM events GROUP BY event', 'events_df', 'Recent events'),
                            pythonNode('print(events_df.head())', 'Summarize'),
                        ],
                    },
                },
            ],
        })
    })

    it('recomputes edits against the latest notebook after a collab conflict', async () => {
        const conflict = new PostHogApiError({
            status: 409,
            statusText: 'Conflict',
            body: '{"code":"conflict"}',
            url: 'https://app.posthog.com/api/projects/42/notebooks/abc123/collab/save/',
            method: 'POST',
        })
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Hello')),
            })
            .mockRejectedValueOnce(conflict)
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 4,
                title: 'Notebook',
                content: doc(paragraph('Hello'), paragraph('Remote edit')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 5,
                title: 'Notebook',
                content: doc(paragraph('Hello'), paragraph('Remote edit'), paragraph('Agent edit')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 1,
            edits: [{ type: 'append', nodes: [paragraph('Agent edit')] }],
        })

        const retryBody = bodyForCall(requestMock, 3)
        expect(retryBody).toMatchObject({
            version: 4,
            text_content: 'Hello\nRemote edit\nAgent edit',
            content: doc(paragraph('Hello'), paragraph('Remote edit'), paragraph('Agent edit')),
            steps: [
                {
                    stepType: 'replace',
                    from: 20,
                    to: 20,
                    slice: { content: [paragraph('Agent edit')] },
                },
            ],
        })
    })

    it('builds text replacement steps with ProseMirror positions', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('Hello world')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Hello PostHog')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [{ type: 'replace_text', find: 'world', replace: 'PostHog', all_occurrences: false, occurrence: 1 }],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'Hello PostHog',
            content: doc(paragraph('Hello PostHog')),
            steps: [
                {
                    stepType: 'replace',
                    from: 7,
                    to: 12,
                    slice: { content: [{ type: 'text', text: 'PostHog' }] },
                },
            ],
        })
    })

    it('replaces all text occurrences without matching replacement text again', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('http http')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('https https')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [{ type: 'replace_text', find: 'http', replace: 'https', all_occurrences: true, occurrence: 1 }],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'https https',
            content: doc(paragraph('https https')),
            steps: [
                {
                    stepType: 'replace',
                    from: 1,
                    to: 5,
                    slice: { content: [{ type: 'text', text: 'https' }] },
                },
                {
                    stepType: 'replace',
                    from: 7,
                    to: 11,
                    slice: { content: [{ type: 'text', text: 'https' }] },
                },
            ],
        })
    })

    it('replaces all query attribute occurrences without matching replacement text again', async () => {
        const oldQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: "SELECT 'http' AS url\nUNION ALL SELECT 'http'" },
            display: 'ActionsTable',
        }
        const newQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: "SELECT 'https' AS url\nUNION ALL SELECT 'https'" },
            display: 'ActionsTable',
        }
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(queryNode(oldQuery, 'URLs')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(queryNode(newQuery, 'URLs')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [{ type: 'replace_text', find: 'http', replace: 'https', all_occurrences: true, occurrence: 1 }],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            content: doc(queryNode(newQuery, 'URLs')),
            steps: [
                {
                    stepType: 'replace',
                    from: 0,
                    to: 1,
                    slice: { content: [queryNode(newQuery, 'URLs')] },
                },
            ],
        })
    })

    it('inserts nodes after an exact heading match', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(heading('Summary'), paragraph('Existing')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(heading('Summary'), paragraph('Inserted'), paragraph('Existing')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'insert_after_heading',
                    heading: 'Summary',
                    occurrence: 1,
                    nodes: [paragraph('Inserted')],
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            content: doc(heading('Summary'), paragraph('Inserted'), paragraph('Existing')),
            steps: [
                {
                    stepType: 'replace',
                    from: 9,
                    to: 9,
                    slice: { content: [paragraph('Inserted')] },
                },
            ],
        })
    })

    it('inserts plain content after a text anchor', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('First anchor'), paragraph('Last block')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('First anchor'), paragraph('Inserted'), paragraph('Last block')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'insert_after',
                    anchor: 'First anchor',
                    occurrence: 1,
                    content: 'Inserted',
                    content_format: 'plain_text',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'First anchor\nInserted\nLast block',
            content: doc(paragraph('First anchor'), paragraph('Inserted'), paragraph('Last block')),
            steps: [
                {
                    stepType: 'replace',
                    from: 14,
                    to: 14,
                    slice: { content: [paragraph('Inserted')] },
                },
            ],
        })
    })

    it('inserts plain content before a text anchor', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('First block'), paragraph('Last anchor')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('First block'), paragraph('Inserted'), paragraph('Last anchor')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'insert_before',
                    anchor: 'Last anchor',
                    occurrence: 1,
                    content: 'Inserted',
                    content_format: 'plain_text',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'First block\nInserted\nLast anchor',
            content: doc(paragraph('First block'), paragraph('Inserted'), paragraph('Last anchor')),
            steps: [
                {
                    stepType: 'replace',
                    from: 13,
                    to: 13,
                    slice: { content: [paragraph('Inserted')] },
                },
            ],
        })
    })

    it('inserts nodes between exact text anchors in top-level blocks', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('Before this anchor'), paragraph('After that anchor')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Before this anchor'), paragraph('Inserted'), paragraph('After that anchor')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'insert_between',
                    after: 'this anchor',
                    before: 'that anchor',
                    after_occurrence: 1,
                    before_occurrence: 1,
                    content: 'Inserted',
                    content_format: 'plain_text',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'Before this anchor\nInserted\nAfter that anchor',
            content: doc(paragraph('Before this anchor'), paragraph('Inserted'), paragraph('After that anchor')),
            steps: [
                {
                    stepType: 'replace',
                    from: 20,
                    to: 20,
                    slice: { content: [paragraph('Inserted')] },
                },
            ],
        })
    })

    it('replaces a whole top-level block using an exact text anchor', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('Keep this'), paragraph('replace this block'), paragraph('Keep that')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Keep this'), hogqlNode('SELECT 1'), paragraph('Keep that')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'replace_block',
                    anchor: 'replace this block',
                    occurrence: 1,
                    content: '<hogql>\nSELECT 1\n</hogql>',
                    content_format: 'markdown',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            content: doc(paragraph('Keep this'), hogqlNode('SELECT 1'), paragraph('Keep that')),
            steps: [
                {
                    stepType: 'replace',
                    from: 11,
                    to: 31,
                    slice: { content: [hogqlNode('SELECT 1')] },
                },
            ],
        })
    })

    it('replaces a top-level node array copied from notebook content', async () => {
        const originalContent = [paragraph('A'), paragraph('B'), paragraph('C')]
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: { type: 'doc', content: originalContent },
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Replacement')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            old_value: originalContent,
            new_value: paragraph('Replacement'),
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: 'Replacement',
            content: doc(paragraph('Replacement')),
            steps: [
                {
                    stepType: 'replace',
                    from: 0,
                    to: 9,
                    slice: { content: [paragraph('Replacement')] },
                },
            ],
        })
    })

    it('uses heading anchors as section ranges when replacing query text', async () => {
        const oldQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: 'SELECT event\nFROM events\nLIMIT 20' },
            display: 'ActionsTable',
        }
        const newQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: 'SELECT event\nFROM events\nLIMIT 100' },
            display: 'ActionsTable',
        }
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(
                    headingWithLevel(2, 'Device & browser'),
                    paragraph('This section compares device/browser combinations.'),
                    queryNode(oldQuery, 'Device type by segment'),
                    headingWithLevel(2, 'Next section'),
                    queryNode({
                        kind: 'DataVisualizationNode',
                        source: { kind: 'HogQLQuery', query: 'SELECT * FROM events LIMIT 20' },
                        display: 'ActionsTable',
                    })
                ),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(
                    headingWithLevel(2, 'Device & browser'),
                    paragraph('This section compares device/browser combinations.'),
                    queryNode(newQuery, 'Device type by segment'),
                    headingWithLevel(2, 'Next section'),
                    queryNode({
                        kind: 'DataVisualizationNode',
                        source: { kind: 'HogQLQuery', query: 'SELECT * FROM events LIMIT 20' },
                        display: 'ActionsTable',
                    })
                ),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'replace_text',
                    anchor: 'Device & browser',
                    occurrence: 1,
                    find: 'LIMIT 20',
                    replace: 'LIMIT 100',
                    all_occurrences: false,
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            content: doc(
                headingWithLevel(2, 'Device & browser'),
                paragraph('This section compares device/browser combinations.'),
                queryNode(newQuery, 'Device type by segment'),
                headingWithLevel(2, 'Next section'),
                queryNode({
                    kind: 'DataVisualizationNode',
                    source: { kind: 'HogQLQuery', query: 'SELECT * FROM events LIMIT 20' },
                    display: 'ActionsTable',
                })
            ),
            steps: [
                {
                    stepType: 'replace',
                    from: 70,
                    to: 71,
                    slice: { content: [queryNode(newQuery, 'Device type by segment')] },
                },
            ],
        })
    })

    it('replaces text inside a query node by title anchor without rebuilding the whole block', async () => {
        const oldQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: 'SELECT event\nFROM events\nLIMIT 40' },
            display: 'ActionsTable',
        }
        const newQuery = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: 'SELECT event\nFROM events\nLIMIT 100' },
            display: 'ActionsTable',
        }
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(queryNode(oldQuery, 'Event retention lift (sorted by lift desc)'), paragraph('Keep')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(queryNode(newQuery, 'Event retention lift (sorted by lift desc)'), paragraph('Keep')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'replace_text',
                    anchor: 'Event retention lift (sorted by lift desc)',
                    occurrence: 1,
                    find: 'LIMIT 40',
                    replace: 'LIMIT 100',
                    all_occurrences: false,
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content:
                '<query title="Event retention lift (sorted by lift desc)">\n' +
                JSON.stringify(newQuery) +
                '\n</query>\nKeep',
            content: doc(queryNode(newQuery, 'Event retention lift (sorted by lift desc)'), paragraph('Keep')),
            steps: [
                {
                    stepType: 'replace',
                    from: 0,
                    to: 1,
                    slice: { content: [queryNode(newQuery, 'Event retention lift (sorted by lift desc)')] },
                },
            ],
        })
    })

    it('replaces text inside an executable SQL cell by title anchor', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(hogqlNode('SELECT * FROM events LIMIT 40', 'events_df', 'Recent events')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(hogqlNode('SELECT * FROM events LIMIT 100', 'events_df', 'Recent events')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'replace_text',
                    anchor: 'Recent events',
                    occurrence: 1,
                    find: 'LIMIT 40',
                    replace: 'LIMIT 100',
                    all_occurrences: false,
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content:
                '<hogql title="Recent events" return_variable="events_df">\nSELECT * FROM events LIMIT 100\n</hogql>',
            content: doc(hogqlNode('SELECT * FROM events LIMIT 100', 'events_df', 'Recent events')),
            steps: [
                {
                    stepType: 'replace',
                    from: 0,
                    to: 1,
                    slice: { content: [hogqlNode('SELECT * FROM events LIMIT 100', 'events_df', 'Recent events')] },
                },
            ],
        })
    })

    it('replaces an existing executable analysis cell by title anchor', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(
                    hogqlNode('SELECT * FROM events LIMIT 10', 'events_df', 'Recent events'),
                    paragraph('Keep')
                ),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(pythonNode('print(events_df.head())', 'Summarize'), paragraph('Keep')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [
                {
                    type: 'replace_block',
                    anchor: 'Recent events',
                    occurrence: 1,
                    content: '<python title="Summarize">\nprint(events_df.head())\n</python>',
                    content_format: 'markdown',
                },
            ],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            version: 2,
            text_content: '<python title="Summarize">\nprint(events_df.head())\n</python>\nKeep',
            content: doc(pythonNode('print(events_df.head())', 'Summarize'), paragraph('Keep')),
            steps: [
                {
                    stepType: 'replace',
                    from: 0,
                    to: 1,
                    slice: { content: [pythonNode('print(events_df.head())', 'Summarize')] },
                },
            ],
        })
    })

    it('rejects executable analysis cells when the notebook-python flag is off', async () => {
        mockIsFeatureFlagEnabled.mockResolvedValue(false)
        const requestMock = vi.fn()
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await expect(
            tool.handler(context, {
                short_id: 'abc123',
                max_retries: 3,
                edits: [
                    {
                        type: 'append',
                        content: '<hogql>\nSELECT 1\n</hogql>',
                        content_format: 'markdown',
                    },
                ],
            })
        ).rejects.toThrow('notebook-python feature flag')
        expect(requestMock).not.toHaveBeenCalled()
    })

    it('rejects executable replacement nodes when the notebook-python flag is off', async () => {
        mockIsFeatureFlagEnabled.mockResolvedValue(false)
        const requestMock = vi.fn()
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await expect(
            tool.handler(context, {
                short_id: 'abc123',
                old_value: paragraph('Replace me'),
                new_value: pythonNode('print("blocked")'),
            })
        ).rejects.toThrow('notebook-python feature flag')
        expect(requestMock).not.toHaveBeenCalled()
    })

    it('recomputes insert_between positions after a collab conflict', async () => {
        const conflict = new PostHogApiError({
            status: 409,
            statusText: 'Conflict',
            body: '{"code":"conflict"}',
            url: 'https://app.posthog.com/api/projects/42/notebooks/abc123/collab/save/',
            method: 'POST',
        })
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(paragraph('Before this anchor'), paragraph('After that anchor')),
            })
            .mockRejectedValueOnce(conflict)
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(paragraph('Before this anchor'), paragraph('Remote edit'), paragraph('After that anchor')),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 4,
                title: 'Notebook',
                content: doc(
                    paragraph('Before this anchor'),
                    paragraph('Remote edit'),
                    paragraph('Inserted'),
                    paragraph('After that anchor')
                ),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 1,
            edits: [
                {
                    type: 'insert_between',
                    after: 'this anchor',
                    before: 'that anchor',
                    after_occurrence: 1,
                    before_occurrence: 1,
                    nodes: [paragraph('Inserted')],
                },
            ],
        })

        const retryBody = bodyForCall(requestMock, 3)
        expect(retryBody).toMatchObject({
            version: 3,
            content: doc(
                paragraph('Before this anchor'),
                paragraph('Remote edit'),
                paragraph('Inserted'),
                paragraph('After that anchor')
            ),
            steps: [
                {
                    stepType: 'replace',
                    from: 33,
                    to: 33,
                    slice: { content: [paragraph('Inserted')] },
                },
            ],
        })
    })

    it('treats empty text blocks as non-leaf ProseMirror nodes when positioning appends', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 2,
                title: 'Notebook',
                content: doc(emptyParagraph()),
            })
            .mockResolvedValueOnce({
                short_id: 'abc123',
                version: 3,
                title: 'Notebook',
                content: doc(emptyParagraph(), paragraph('After empty block')),
            })
        const context = createMockContext(requestMock)
        const tool = editNotebook()

        await tool.handler(context, {
            short_id: 'abc123',
            max_retries: 3,
            edits: [{ type: 'append', nodes: [paragraph('After empty block')] }],
        })

        const body = bodyForCall(requestMock, 1)
        expect(body).toMatchObject({
            steps: [
                {
                    stepType: 'replace',
                    from: 2,
                    to: 2,
                    slice: { content: [paragraph('After empty block')] },
                },
            ],
        })
    })
})

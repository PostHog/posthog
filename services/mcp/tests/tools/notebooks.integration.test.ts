import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    getToolByName,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import type { Context } from '@/tools/types'

describe('Notebooks', { concurrent: false }, () => {
    let context: Context
    const createdNotebookShortIds: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        const projectId = TEST_PROJECT_ID!
        for (const shortId of createdNotebookShortIds) {
            try {
                await context.api.request({
                    method: 'PATCH',
                    path: `/api/projects/${projectId}/notebooks/${shortId}/`,
                    body: { deleted: true },
                })
            } catch (error) {
                console.warn(`Failed to cleanup notebook ${shortId}:`, error)
            }
        }
        createdNotebookShortIds.length = 0
    })

    // notebooks-create writes markdown notebooks, so the legacy JSON mode of notebook-edit needs a
    // notebook created through the REST API, which still accepts a ProseMirror document.
    async function createLegacyNotebook(title: string, content: Record<string, unknown>): Promise<any> {
        return await context.api.request({
            method: 'POST',
            path: `/api/projects/${TEST_PROJECT_ID!}/notebooks/`,
            body: { title, content },
        })
    }

    function markdownDocument(markdown: string): Record<string, unknown> {
        return {
            type: 'doc',
            content: [{ type: 'ph-markdown-notebook', attrs: { nodeId: 'markdown-notebook-v2', markdown } }],
        }
    }

    describe('notebooks-create tool', () => {
        const createTool = getToolByName('notebooks-create')

        it('should create a notebook with title only', async () => {
            const params = {
                title: generateUniqueKey('Test Notebook'),
            }

            const result = await createTool.handler(context, params)
            const notebook = parseToolResponse(result)

            expect(notebook.short_id).toBeTruthy()
            expect(notebook.title).toBe(params.title)
            expect(notebook.version).toBe(0)
            expect(notebook.deleted).toBe(false)
            expect(notebook._posthogUrl).toContain('/notebooks/')

            createdNotebookShortIds.push(notebook.short_id)
        })

        it('should create a markdown notebook with a body', async () => {
            const params = {
                title: generateUniqueKey('Markdown Notebook'),
                markdown: '## Test heading\n\nTest paragraph',
            }

            const result = await createTool.handler(context, params)
            const notebook = parseToolResponse(result)

            expect(notebook.short_id).toBeTruthy()
            expect(notebook.title).toBe(params.title)
            expect(notebook.content.content).toEqual([
                expect.objectContaining({
                    type: 'ph-markdown-notebook',
                    attrs: expect.objectContaining({ markdown: `# ${params.title}\n\n${params.markdown}` }),
                }),
            ])

            createdNotebookShortIds.push(notebook.short_id)
        })
    })

    describe('notebooks-list tool', () => {
        const listTool = getToolByName('notebooks-list')

        it('should return notebooks with proper structure', async () => {
            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
            expect(response._posthogUrl).toContain('/notebooks')
        })
    })

    describe('notebooks-retrieve tool', () => {
        const createTool = getToolByName('notebooks-create')
        const retrieveTool = getToolByName('notebooks-retrieve')

        it('should get a specific notebook by short_id', async () => {
            const createResult = await createTool.handler(context, {
                title: generateUniqueKey('Retrieve Test Notebook'),
            })
            const created = parseToolResponse(createResult)
            createdNotebookShortIds.push(created.short_id)

            const result = await retrieveTool.handler(context, { short_id: created.short_id })
            const retrieved = parseToolResponse(result)

            expect(retrieved.short_id).toBe(created.short_id)
            expect(retrieved.title).toContain('Retrieve Test Notebook')
            expect(retrieved).toHaveProperty('version')
            expect(retrieved).toHaveProperty('content')
        })
    })

    describe('notebooks-partial-update tool', () => {
        const createTool = getToolByName('notebooks-create')
        const updateTool = getToolByName('notebooks-partial-update')

        it('should update notebook title', async () => {
            const createResult = await createTool.handler(context, {
                title: generateUniqueKey('Update Test Notebook'),
            })
            const created = parseToolResponse(createResult)
            createdNotebookShortIds.push(created.short_id)

            const updateResult = await updateTool.handler(context, {
                short_id: created.short_id,
                title: 'Updated Title',
            })
            const updated = parseToolResponse(updateResult)

            expect(updated.short_id).toBe(created.short_id)
            expect(updated.title).toBe('Updated Title')
        })

        it('should update notebook content with version for concurrency control', async () => {
            const createResult = await createTool.handler(context, {
                title: generateUniqueKey('Version Test Notebook'),
                markdown: 'Original',
            })
            const created = parseToolResponse(createResult)
            createdNotebookShortIds.push(created.short_id)
            expect(created.version).toBe(0)

            const updateResult = await updateTool.handler(context, {
                short_id: created.short_id,
                version: 0,
                content: markdownDocument('# Version Test Notebook\n\nUpdated'),
            })
            const updated = parseToolResponse(updateResult)

            expect(updated.version).toBe(1)
        })
    })

    describe('notebook-edit tool', () => {
        const retrieveTool = getToolByName('notebooks-retrieve')
        const editTool = getToolByName('notebook-edit')

        it('should replace a paragraph by value and bump the version', async () => {
            const created = await createLegacyNotebook(generateUniqueKey('Edit Test Notebook'), {
                type: 'doc',
                content: [
                    { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Heading' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Original paragraph.' }] },
                ],
            })
            createdNotebookShortIds.push(created.short_id)

            const editResult = await editTool.handler(context, {
                short_id: created.short_id,
                old_value: { type: 'paragraph', content: [{ type: 'text', text: 'Original paragraph.' }] },
                new_value: { type: 'paragraph', content: [{ type: 'text', text: 'Edited paragraph.' }] },
            })
            const edited = parseToolResponse(editResult)

            expect(edited.short_id).toBe(created.short_id)
            expect(edited.version).toBe(created.version + 1)
            const serialized = JSON.stringify(edited.content)
            expect(serialized).toContain('Edited paragraph.')
            expect(serialized).not.toContain('Original paragraph.')
        })

        it('should replace every occurrence when replace_all is true', async () => {
            const created = await createLegacyNotebook(generateUniqueKey('Edit Replace-All Notebook'), {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                ],
            })
            createdNotebookShortIds.push(created.short_id)

            const editResult = await editTool.handler(context, {
                short_id: created.short_id,
                old_value: { type: 'text', text: 'duplicate' },
                new_value: { type: 'text', text: 'unique' },
                replace_all: true,
            })
            const edited = parseToolResponse(editResult)

            const serialized = JSON.stringify(edited.content)
            expect(serialized).not.toContain('"text":"duplicate"')
            expect((serialized.match(/"text":"unique"/g) || []).length).toBe(2)
        })

        it('should error when old_value matches multiple places without replace_all', async () => {
            const created = await createLegacyNotebook(generateUniqueKey('Edit Ambiguous Notebook'), {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                ],
            })
            createdNotebookShortIds.push(created.short_id)

            await expect(
                editTool.handler(context, {
                    short_id: created.short_id,
                    old_value: { type: 'text', text: 'duplicate' },
                    new_value: { type: 'text', text: 'unique' },
                })
            ).rejects.toThrow(/matches 2 places/)

            // Notebook untouched.
            const retrieveResult = await retrieveTool.handler(context, { short_id: created.short_id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.version).toBe(created.version)
        })

        it('should error when old_value is not found', async () => {
            const created = await createLegacyNotebook(generateUniqueKey('Edit Missing Notebook'), {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }],
            })
            createdNotebookShortIds.push(created.short_id)

            await expect(
                editTool.handler(context, {
                    short_id: created.short_id,
                    old_value: { type: 'text', text: 'Nope' },
                    new_value: { type: 'text', text: 'Something' },
                })
            ).rejects.toThrow(/was not found/)
        })
    })

    describe('notebooks-destroy tool', () => {
        const createTool = getToolByName('notebooks-create')
        const destroyTool = getToolByName('notebooks-destroy')

        it('should soft-delete a notebook', async () => {
            const createResult = await createTool.handler(context, {
                title: generateUniqueKey('Delete Test Notebook'),
            })
            const created = parseToolResponse(createResult)

            const deleteResult = await destroyTool.handler(context, {
                short_id: created.short_id,
            })
            const deleted = parseToolResponse(deleteResult)

            expect(deleted.deleted).toBe(true)
        })
    })

    describe('Notebook workflow', () => {
        it('should support full CRUD workflow', async () => {
            const createTool = getToolByName('notebooks-create')
            const retrieveTool = getToolByName('notebooks-retrieve')
            const updateTool = getToolByName('notebooks-partial-update')
            const destroyTool = getToolByName('notebooks-destroy')

            // Create
            const createResult = await createTool.handler(context, {
                title: generateUniqueKey('Workflow Notebook'),
                markdown: 'Initial content',
            })
            const created = parseToolResponse(createResult)
            expect(created.short_id).toBeTruthy()

            // Retrieve
            const getResult = await retrieveTool.handler(context, { short_id: created.short_id })
            const retrieved = parseToolResponse(getResult)
            expect(retrieved.short_id).toBe(created.short_id)

            // Update
            const updateResult = await updateTool.handler(context, {
                short_id: created.short_id,
                title: 'Updated Workflow Notebook',
                version: retrieved.version,
                content: markdownDocument('# Updated Workflow Notebook\n\nInitial content\n\nAppended content'),
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.title).toBe('Updated Workflow Notebook')
            expect(updated.version).toBe(retrieved.version + 1)

            // Delete
            const deleteResult = await destroyTool.handler(context, { short_id: created.short_id })
            const deleted = parseToolResponse(deleteResult)
            expect(deleted.deleted).toBe(true)
        })
    })
})

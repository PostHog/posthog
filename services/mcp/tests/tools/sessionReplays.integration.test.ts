import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/replay'
import type { Context } from '@/tools/types'

describe('Session Replays', { concurrent: false }, () => {
    let context: Context

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('Session Recordings', () => {
        const listTool = GENERATED_TOOLS['session-recordings-list']!()
        const getTool = GENERATED_TOOLS['session-recording-get']!()

        describe('session-recordings-list tool', () => {
            it('should return paginated structure', async () => {
                const result = await listTool.handler(context, {})
                const data = parseToolResponse(result)

                expect(Array.isArray(data.results)).toBe(true)
                expect(typeof data._posthogUrl).toBe('string')
                expect(data._posthogUrl).toContain('/replay')
            })

            it('should respect the limit parameter', async () => {
                const result = await listTool.handler(context, { limit: 1 })
                const data = parseToolResponse(result)

                expect(Array.isArray(data.results)).toBe(true)
                expect(data.results.length).toBeLessThanOrEqual(1)
            })
        })

        describe('session-recording-get tool', () => {
            it('should throw for a non-existent ID', async () => {
                await expect(getTool.handler(context, { id: 'nonexistent-session-id' })).rejects.toThrow()
            })
        })
    })

    describe('Session Recording Playlists', () => {
        const listTool = GENERATED_TOOLS['session-recording-playlists-list']!()
        const getTool = GENERATED_TOOLS['session-recording-playlist-get']!()
        const createTool = GENERATED_TOOLS['session-recording-playlist-create']!()
        const updateTool = GENERATED_TOOLS['session-recording-playlist-update']!()

        const createdPlaylistIds: string[] = []

        afterEach(async () => {
            for (const shortId of createdPlaylistIds) {
                try {
                    await updateTool.handler(context, { short_id: shortId, deleted: true })
                } catch {
                    // best effort
                }
            }
            createdPlaylistIds.length = 0
        })

        describe('session-recording-playlists-list tool', () => {
            it('should return paginated structure', async () => {
                const result = await listTool.handler(context, {})
                const data = parseToolResponse(result)

                expect(typeof data.count).toBe('number')
                expect(Array.isArray(data.results)).toBe(true)
                expect(typeof data._posthogUrl).toBe('string')
                expect(data._posthogUrl).toContain('/replay')
            })

            it('should respect the limit parameter', async () => {
                const result = await listTool.handler(context, { limit: 1 })
                const data = parseToolResponse(result)

                expect(Array.isArray(data.results)).toBe(true)
                expect(data.results.length).toBeLessThanOrEqual(1)
            })
        })

        describe('session-recording-playlist-create tool', () => {
            it('should create a collection playlist', async () => {
                const name = `test-playlist-${generateUniqueKey('collection')}`
                const result = await createTool.handler(context, {
                    name,
                    type: 'collection',
                    description: 'Test collection playlist',
                })
                const playlist = parseToolResponse(result)
                createdPlaylistIds.push(playlist.short_id)

                expect(playlist.short_id).toBeTruthy()
                expect(playlist.name).toBe(name)
                expect(playlist.type).toBe('collection')
                expect(playlist.description).toBe('Test collection playlist')
            })

            it('should create a filters playlist', async () => {
                const name = `test-playlist-${generateUniqueKey('filters')}`
                const result = await createTool.handler(context, {
                    name,
                    type: 'filters',
                    filters: { events: [] },
                })
                const playlist = parseToolResponse(result)
                createdPlaylistIds.push(playlist.short_id)

                expect(playlist.short_id).toBeTruthy()
                expect(playlist.name).toBe(name)
                expect(playlist.type).toBe('filters')
            })
        })

        describe('session-recording-playlist-get tool', () => {
            it('should retrieve a specific playlist by short_id', async () => {
                const created = await createTool.handler(context, {
                    name: `test-playlist-${generateUniqueKey('get')}`,
                    type: 'collection',
                })
                const createdPlaylist = parseToolResponse(created)
                createdPlaylistIds.push(createdPlaylist.short_id)

                const result = await getTool.handler(context, { short_id: createdPlaylist.short_id })
                const playlist = parseToolResponse(result)

                expect(playlist.short_id).toBe(createdPlaylist.short_id)
                expect(playlist.name).toBe(createdPlaylist.name)
            })

            it('should throw for a non-existent short_id', async () => {
                await expect(getTool.handler(context, { short_id: 'nonexistent00' })).rejects.toThrow()
            })
        })

        describe('session-recording-playlist-update tool', () => {
            it('should update the name of a playlist', async () => {
                const created = await createTool.handler(context, {
                    name: `test-playlist-${generateUniqueKey('update')}`,
                    type: 'collection',
                })
                const playlist = parseToolResponse(created)
                createdPlaylistIds.push(playlist.short_id)

                const newName = `renamed-${generateUniqueKey('playlist')}`
                const result = await updateTool.handler(context, {
                    short_id: playlist.short_id,
                    name: newName,
                })
                const updated = parseToolResponse(result)

                expect(updated.name).toBe(newName)
                expect(updated.short_id).toBe(playlist.short_id)
            })

            it('should update the description', async () => {
                const created = await createTool.handler(context, {
                    name: `test-playlist-${generateUniqueKey('desc')}`,
                    type: 'collection',
                })
                const playlist = parseToolResponse(created)
                createdPlaylistIds.push(playlist.short_id)

                const result = await updateTool.handler(context, {
                    short_id: playlist.short_id,
                    description: 'Updated description',
                })
                const updated = parseToolResponse(result)

                expect(updated.description).toBe('Updated description')
            })

            it('should toggle pinned status', async () => {
                const created = await createTool.handler(context, {
                    name: `test-playlist-${generateUniqueKey('pin')}`,
                    type: 'collection',
                })
                const playlist = parseToolResponse(created)
                createdPlaylistIds.push(playlist.short_id)

                const pinResult = await updateTool.handler(context, {
                    short_id: playlist.short_id,
                    pinned: true,
                })
                expect(parseToolResponse(pinResult).pinned).toBe(true)

                const unpinResult = await updateTool.handler(context, {
                    short_id: playlist.short_id,
                    pinned: false,
                })
                expect(parseToolResponse(unpinResult).pinned).toBe(false)
            })
        })

        describe('Playlists workflow', () => {
            it('should support a full create → retrieve → update → soft-delete lifecycle', async () => {
                const name = `workflow-playlist-${generateUniqueKey('lifecycle')}`

                // Create
                const createResult = await createTool.handler(context, {
                    name,
                    type: 'collection',
                    description: 'Lifecycle test',
                })
                const created = parseToolResponse(createResult)
                expect(created.short_id).toBeTruthy()
                expect(created.name).toBe(name)

                // Retrieve
                const getResult = await getTool.handler(context, { short_id: created.short_id })
                const retrieved = parseToolResponse(getResult)
                expect(retrieved.short_id).toBe(created.short_id)

                // Update
                const updatedName = `${name}-updated`
                const updateResult = await updateTool.handler(context, {
                    short_id: created.short_id,
                    name: updatedName,
                    pinned: true,
                })
                const updated = parseToolResponse(updateResult)
                expect(updated.name).toBe(updatedName)
                expect(updated.pinned).toBe(true)

                // Soft-delete
                const deleteResult = await updateTool.handler(context, {
                    short_id: created.short_id,
                    deleted: true,
                })
                const deleted = parseToolResponse(deleteResult)
                expect(deleted.deleted).toBe(true)
            })

            it('should appear in list results after creation', async () => {
                const name = `list-check-playlist-${generateUniqueKey('appear')}`

                const createResult = await createTool.handler(context, {
                    name,
                    type: 'collection',
                })
                const created = parseToolResponse(createResult)
                createdPlaylistIds.push(created.short_id)

                const listResult = await listTool.handler(context, {})
                const data = parseToolResponse(listResult)

                const found = data.results.find((p: any) => p.short_id === created.short_id)
                expect(found).toBeTruthy()
                expect(found.name).toBe(name)
            })
        })
    })
})

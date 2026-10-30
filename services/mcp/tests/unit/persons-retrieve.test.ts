import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/persons'
import type { Context } from '@/tools/types'

const PERSON_UUID = '0190a5b2-7c3d-7e4f-8a9b-0c1d2e3f4a5b'

function createContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request,
            getProjectBaseUrl: () => 'https://us.posthog.com/project/42',
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
    } as unknown as Context
}

describe('persons-retrieve', () => {
    const tool = GENERATED_TOOLS['persons-retrieve']!()

    it.each([
        ['numeric id', '12345'],
        ['uuid', PERSON_UUID],
    ])('links to the person UUID route when looked up by %s', async (_label, id) => {
        const request = vi.fn().mockResolvedValue({ id: 12345, uuid: PERSON_UUID, distinct_ids: ['user-1'] })

        await expect(tool.handler(createContext(request), { id })).resolves.toMatchObject({
            _posthogUrl: `https://us.posthog.com/project/42/persons/${PERSON_UUID}`,
        })
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: `/api/projects/42/persons/${id}/`,
        })
    })
})

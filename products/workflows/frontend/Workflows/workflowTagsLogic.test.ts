import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowTagsLogic } from './workflowTagsLogic'

describe('workflowTagsLogic', () => {
    let logic: ReturnType<typeof workflowTagsLogic.build>
    let createdNames: string[]

    beforeEach(() => {
        createdNames = []
        useMocks({
            get: {
                '/api/projects/:team_id/tags/pinned/': () => [
                    200,
                    [
                        { id: 'tag-1', name: 'marketing', pinned: true },
                        { id: 'tag-2', name: 'onboarding', pinned: true },
                    ],
                ],
            },
            post: {
                '/api/projects/:team_id/tags/': async ({ request }) => {
                    const body = (await request.json()) as { name: string }
                    createdNames.push(body.name)
                    // The server trims and lowercases, so the response is the normalized name.
                    return [201, { id: 'tag-3', name: body.name.trim().toLowerCase(), pinned: true }]
                },
            },
        })
        initKeaTests()
        logic = workflowTagsLogic()
        logic.mount()
        logic.actions.loadPinnedTags()
    })

    it('treats a differently cased or padded name as the existing tag', async () => {
        await expectLogic(logic).toDispatchActions(['loadPinnedTagsSuccess'])

        logic.actions.setNewTagName('  Marketing ')

        await expectLogic(logic).toMatchValues({
            normalizedNewTagName: 'marketing',
            newTagExists: true,
        })
        expect(logic.values.matchingTags.map((tag) => tag.name)).toEqual(['marketing'])
    })

    it('creates a new tag under its normalized name and sorts it into the list', async () => {
        await expectLogic(logic).toDispatchActions(['loadPinnedTagsSuccess'])

        logic.actions.setNewTagName('Growth')
        await expectLogic(logic, () => {
            logic.actions.createTag(logic.values.normalizedNewTagName)
        }).toDispatchActions(['createTagSuccess'])

        expect(createdNames).toEqual(['growth'])
        expect(logic.values.pinnedTagNames).toEqual(['growth', 'marketing', 'onboarding'])
        expect(logic.values.newTagName).toBe('')
    })
})

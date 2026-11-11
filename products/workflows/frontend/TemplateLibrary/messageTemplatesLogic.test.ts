import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { messageTemplatesLogic, saveTemplateTags } from './messageTemplatesLogic'
import type { MessageTemplate } from './types'

const template = (id: string, name: string, tags: string[]): MessageTemplate =>
    ({ id, name, description: '', tags }) as unknown as MessageTemplate

describe('messageTemplatesLogic', () => {
    let logic: ReturnType<typeof messageTemplatesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': {
                    results: [
                        template('a', 'Welcome', ['growth', 'onboarding']),
                        template('b', 'Invoice', ['billing']),
                        template('c', 'Plain', []),
                    ],
                },
            },
        })
        initKeaTests()
        logic = messageTemplatesLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['tag filter', { tagsFilter: ['growth'] }, ['Welcome']],
        ['tag filter matching any', { tagsFilter: ['growth', 'billing'] }, ['Welcome', 'Invoice']],
        ['search by tag name', { search: 'onboard' }, ['Welcome']],
        ['search by name still works', { search: 'invoice' }, ['Invoice']],
    ])('filters the library by %s', async (_name, filters: any, expected) => {
        await expectLogic(logic).toFinishAllListeners()
        if (filters.tagsFilter) {
            logic.actions.setTagsFilter(filters.tagsFilter)
        }
        if (filters.search) {
            logic.actions.setSearch(filters.search)
        }

        expect(logic.values.filteredTemplates.map((t) => t.name)).toEqual(expected)
    })

    it('saves a tag edit with only the tags, so it never republishes the content', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const bodies: unknown[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, template('a', 'Welcome', ['growth'])]
                },
            },
        })

        await saveTemplateTags(template('a', 'Welcome', []), ['growth'])

        expect(bodies).toEqual([{ tags: ['growth'] }])
        expect(logic.values.templates.find((t) => t.id === 'a')?.tags).toEqual(['growth'])
    })

    it('rejects a failed tag save, so the editor it was opened from stays open', async () => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': () => [400, { detail: 'too many tags' }],
            },
        })

        await expect(saveTemplateTags(template('a', 'Welcome', []), ['growth'])).rejects.toThrow()
        expect(logic.values.templates.find((t) => t.id === 'a')?.tags).toEqual(['growth', 'onboarding'])
    })

    it.each([
        ['loaded in the project tree', true],
        ['not loaded in the project tree', false],
    ])('deletes a template for good and brings it back into its folder on undo, %s', async (_name, inTree) => {
        await expectLogic(logic).toFinishAllListeners()
        const filedAt = (path: string): Record<string, string> => ({
            id: 'file-a',
            path,
            type: 'message_template',
            ref: 'a',
        })
        let deleted = false
        let restoredPath: string | undefined
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': () => [
                    200,
                    { results: deleted ? [] : [template('a', 'Welcome', [])] },
                ],
                '/api/environments/:team_id/file_system/': ({ request }) =>
                    new URL(request.url).searchParams.get('ref') === 'a' && !deleted
                        ? [200, { results: [filedAt(restoredPath ?? 'Campaigns/Welcome')], count: 1 }]
                        : [200, { results: [], count: 0 }],
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                    if (deleted) {
                        return [404, { detail: 'Not found.' }]
                    }
                    deleted = ((await request.json()) as { deleted: boolean }).deleted
                    return [200, template('a', 'Welcome', [])]
                },
            },
            post: {
                '/api/environments/:team_id/file_system/undo_delete/': async ({ request }) => {
                    const { items } = (await request.json()) as { items: { ref: string; path?: string }[] }
                    deleted = false
                    restoredPath = items[0].path ?? 'Unfiled/Email templates/Welcome'
                    return [200, { undone: items }]
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        projectTreeDataLogic.mount()
        if (inTree) {
            projectTreeDataLogic.actions.addLoadedResults({ results: [filedAt('Campaigns/Welcome')] } as any)
        }
        const toast = jest.spyOn(lemonToast, 'info')

        await expectLogic(logic, () => {
            logic.actions.deleteTemplate(template('a', 'Welcome', []))
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadTemplates()).toFinishAllListeners()
        expect(logic.values.templates.map((t) => t.id)).toEqual([])
        expect(projectTreeDataLogic.values.itemsByRef['message_template::a']).toBeUndefined()

        await toast.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        expect(logic.values.templates.map((t) => t.id)).toEqual(['a'])
        expect(restoredPath).toBe('Campaigns/Welcome')
        expect(projectTreeDataLogic.values.itemsByRef['message_template::a']?.path).toBe(
            inTree ? 'Campaigns/Welcome' : undefined
        )

        toast.mockRestore()
        projectTreeDataLogic.unmount()
    })
})

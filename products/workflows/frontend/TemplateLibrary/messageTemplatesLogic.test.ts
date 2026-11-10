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
                '/api/projects/:team_id/tags': ['billing', 'growth', 'onboarding'],
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

    it('deletes a template for good and brings it back on undo, in the library and the project tree', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const treeEntry = { id: 'file-a', path: 'Unfiled/Email templates/Welcome', type: 'message_template', ref: 'a' }
        let deleted = false
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': () => [
                    200,
                    { results: deleted ? [] : [template('a', 'Welcome', [])] },
                ],
                '/api/environments/:team_id/file_system/': ({ request }) =>
                    new URL(request.url).searchParams.get('ref') === 'a' && !deleted
                        ? [200, { results: [treeEntry], count: 1 }]
                        : [200, { results: [], count: 0 }],
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                    deleted = ((await request.json()) as { deleted: boolean }).deleted
                    return [200, template('a', 'Welcome', [])]
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        projectTreeDataLogic.mount()
        projectTreeDataLogic.actions.addLoadedResults({ results: [treeEntry] } as any)
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
        expect(projectTreeDataLogic.values.itemsByRef['message_template::a']?.path).toBe(
            'Unfiled/Email templates/Welcome'
        )

        toast.mockRestore()
        projectTreeDataLogic.unmount()
    })
})

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
        ['while the tree shows a shortcut to it', true],
        ['while the tree hides it', false],
    ])('deletes a template for good and brings it back into its folder on undo, %s', async (_name, withShortcut) => {
        await expectLogic(logic).toFinishAllListeners()
        let deleted = false
        let restoredPath: string | undefined
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': () => [
                    200,
                    { results: deleted ? [] : [template('a', 'Welcome', [])] },
                ],
                '/api/projects/:team_id/messaging_templates/:id/placement/': () => [
                    200,
                    { path: deleted ? null : (restoredPath ?? 'Campaigns/Welcome') },
                ],
                '/api/environments/:team_id/file_system/': () => [200, { results: [], count: 0 }],
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
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: withShortcut })
        projectTreeDataLogic.mount()
        if (withShortcut) {
            projectTreeDataLogic.actions.addLoadedResults({
                results: [
                    { id: 'file-a', path: 'Campaigns/Welcome', type: 'message_template', ref: 'a' },
                    { id: 'shortcut-a', path: 'Shortcuts/Welcome', type: 'message_template', ref: 'a', shortcut: true },
                ],
            } as any)
        }
        const toast = jest.spyOn(lemonToast, 'info')

        await expectLogic(logic, () => {
            logic.actions.deleteTemplate(template('a', 'Welcome', []))
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadTemplates()).toFinishAllListeners()
        expect(logic.values.templates.map((t) => t.id)).toEqual([])

        await toast.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        expect(logic.values.templates.map((t) => t.id)).toEqual(['a'])
        expect(restoredPath).toBe('Campaigns/Welcome')

        toast.mockRestore()
        projectTreeDataLogic.unmount()
    })

    it('keeps a template when the lookup of its folder fails, and deletes it on retry once the lookup works', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let lookupFails = true
        let deleted = false
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/:id/placement/': () =>
                    lookupFails ? [500, { detail: 'Server error' }] : [200, { path: 'Campaigns/Welcome' }],
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                    deleted = ((await request.json()) as { deleted: boolean }).deleted
                    return [200, template('a', 'Welcome', [])]
                },
            },
        })
        const error = jest.spyOn(lemonToast, 'error')

        await expectLogic(logic, () => {
            logic.actions.deleteTemplate(template('a', 'Welcome', []))
        }).toFinishAllListeners()

        expect(deleted).toBe(false)
        expect(logic.values.templates.map((t) => t.id)).toEqual(['a', 'b', 'c'])
        const retry = error.mock.calls[0][1]?.button
        expect(retry?.label).toBe('Retry')

        lookupFails = false
        await expectLogic(logic, () => {
            void retry?.action()
        }).toFinishAllListeners()

        expect(deleted).toBe(true)
        expect(logic.values.templates.map((t) => t.id)).toEqual(['b', 'c'])
        error.mockRestore()
    })
})

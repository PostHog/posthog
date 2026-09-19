import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { attachedContextItemKey, attachedContextLogic } from 'products/posthog_ai/frontend/api/logics'

import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { PICKED_TEMPLATE_DISMISS_GROUP } from './templateAgentContext'
import { MessageTemplate } from './types'

const AI_FIRST_FLAGS = [
    FEATURE_FLAGS.EMAIL_TEMPLATES_AI_FIRST_NEW,
    FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
    FEATURE_FLAGS.PHAI_SANDBOX_MODE,
]

const NEW_PATH = '/workflows/library/templates/new'

const TEMPLATE: MessageTemplate = {
    id: 'tpl-1',
    name: 'Welcome',
    description: '',
    content: { templating: 'liquid', email: { subject: 'Hi', text: '', html: '<p>Hi</p>', design: {} } as any },
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
    created_by: null,
}

describe('newTemplateAgentLogic', () => {
    let logic: ReturnType<typeof newTemplateAgentLogic.build>

    const setFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = newTemplateAgentLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The flag-off path must stay byte-identical, and exposure is recorded only for a click the composer could answer.
    it.each([
        { name: 'flag on', flags: AI_FIRST_FLAGS, mode: { mode: 'ai' }, exposed: true },
        {
            name: 'flag off',
            flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
            mode: {},
            exposed: true,
        },
        {
            name: 'scene integration off',
            flags: [FEATURE_FLAGS.EMAIL_TEMPLATES_AI_FIRST_NEW],
            mode: {},
            exposed: false,
        },
    ])('startNewTemplate marks the composer route only with $name', async ({ flags, mode, exposed }) => {
        setFlags(flags)
        const recordExposure = jest.spyOn(posthog, 'getFeatureFlag').mockReturnValue(undefined)
        router.actions.push('/workflows/library', {}, {})

        await expectLogic(logic, () => {
            logic.actions.startNewTemplate()
        }).toFinishAllListeners()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(NEW_PATH)
        expect(router.values.searchParams).toEqual(mode)
        expect(recordExposure.mock.calls.map(([flag]) => flag)).toEqual(
            exposed ? [FEATURE_FLAGS.EMAIL_TEMPLATES_AI_FIRST_NEW] : []
        )
        recordExposure.mockRestore()
    })

    // A template started from a sent message has its starting point, and the escape hatch must land in the editor.
    it.each([
        { name: 'an AI entry', path: NEW_PATH, search: { mode: 'ai' }, available: true },
        { name: 'a plain new URL', path: NEW_PATH, search: {}, available: false },
        { name: 'a sent message', path: NEW_PATH, search: { mode: 'ai', messageId: 'msg-1' }, available: false },
        { name: 'the editor mode param', path: NEW_PATH, search: { mode: 'editor' }, available: false },
        {
            name: 'an existing template',
            path: '/workflows/library/templates/tpl-1',
            search: { mode: 'ai' },
            available: false,
        },
    ])('aiComposerAvailable is $available for $name', ({ path, search, available }) => {
        setFlags(AI_FIRST_FLAGS)

        router.actions.push(path, search, {})

        expect(logic.values.aiComposerAvailable).toBe(available)
    })

    it('openEditorFromAiComposer marks the editor route so the composer does not render again', async () => {
        setFlags(AI_FIRST_FLAGS)
        router.actions.push(NEW_PATH, { mode: 'ai' }, {})

        await expectLogic(logic, () => {
            logic.actions.openEditorFromAiComposer()
        }).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ mode: 'editor' })
        expect(logic.values.aiComposerAvailable).toBe(false)
    })

    describe('picked template', () => {
        beforeEach(() => {
            attachedContextLogic.mount()
            router.actions.push(NEW_PATH, { mode: 'ai' }, {})
        })

        afterEach(() => {
            attachedContextLogic.unmount()
        })

        // A dismissal sticks for the group, so a second pick would otherwise never show its attachment.
        it('attaches the pick as context and lifts an earlier dismissal of the attachment', async () => {
            const key = attachedContextItemKey({ type: 'email_template', key: TEMPLATE.id })
            attachedContextLogic.actions.dismissContext(key, PICKED_TEMPLATE_DISMISS_GROUP)

            await expectLogic(logic, () => {
                logic.actions.setPickedTemplate(TEMPLATE)
            }).toFinishAllListeners()

            expect(logic.values.agentContextItems.find((item) => item.type === 'email_template')?.key).toBe(TEMPLATE.id)
            expect(attachedContextLogic.values.dismissedGroups[PICKED_TEMPLATE_DISMISS_GROUP]).toBeUndefined()
        })

        // Removing the attachment is the only way to un-pick, and leaving the page must not carry the pick to the next visit.
        it.each([
            {
                name: 'the attachment is removed',
                act: () =>
                    attachedContextLogic.actions.dismissContext('email_template:tpl-1', PICKED_TEMPLATE_DISMISS_GROUP),
            },
            { name: 'the person leaves the page', act: () => router.actions.push('/workflows/library', {}, {}) },
        ])('clears the pick when $name', async ({ act }) => {
            logic.actions.setPickedTemplate(TEMPLATE)

            await expectLogic(logic, act).toFinishAllListeners()

            expect(logic.values.pickedTemplate).toBeNull()
            expect(logic.values.agentContextItems.some((item) => item.type === 'email_template')).toBe(false)
        })
    })
})

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import preflightFixture from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { attachedContextItemKey, attachedContextLogic } from 'products/posthog_ai/frontend/api/logics'

import { firstRunEmailAgentLogic } from './firstRunEmailAgentLogic'
import { firstRunGalleryLogic } from './firstRunGalleryLogic'
import { firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'

const EMAILS = ['Welcome', 'Next steps'].map((subject, index) => ({
    id: `email_${index + 1}`,
    type: 'function_email',
    name: subject,
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    subject,
                    preheader: `Preview for ${subject}`,
                    text: `Body for ${subject}`,
                    html: `<p>Body for ${subject}</p>`,
                    design: { body: { rows: [] } },
                },
            },
        },
    },
}))

const TEMPLATE = {
    id: 'example-sequence',
    name: 'Example sequence',
    scope: 'global',
    tags: [],
    actions: [
        { id: 'trigger', type: 'trigger', name: 'Signup', config: { type: 'event', filters: {} } },
        ...EMAILS,
        { id: 'exit', type: 'exit', name: 'Done', config: {} },
    ],
    edges: [
        { from: 'trigger', to: 'email_1', type: 'continue' },
        { from: 'email_1', to: 'email_2', type: 'continue' },
        { from: 'email_2', to: 'exit', type: 'continue' },
    ],
    starts_on: { kind: 'event', events: ['signed_up'], detail: '' },
}

describe('firstRunEmailAgentLogic', () => {
    let logic: ReturnType<typeof firstRunEmailAgentLogic.build>
    let editor: ReturnType<typeof firstRunMakeItYoursLogic.build>
    let releasePreflight: () => void
    let preflightResponse: typeof preflightFixture & { anthropic_available: boolean }

    beforeEach(() => {
        const preflightGate = new Promise<void>((resolve) => {
            releasePreflight = resolve
        })
        preflightResponse = { ...preflightFixture, anthropic_available: false }
        useMocks({
            get: {
                '/_preflight': async () => {
                    await preflightGate
                    return [200, preflightResponse]
                },
                '/api/projects/:team_id/hog_flow_templates/': { count: 1, results: [TEMPLATE] },
                '/api/projects/:team_id/event_definitions/': { count: 0, results: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/environments/:team_id/conversations/': { results: [] },
                '/api/billing/usage/team_options/': { team_id_options: [] },
            },
        })
        initKeaTests()
        sessionStorage.clear()
        localStorage.clear()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        attachedContextLogic.mount()
        editor = firstRunMakeItYoursLogic({ templateId: TEMPLATE.id })
        editor.mount()
    })

    afterEach(() => {
        logic?.unmount()
        editor.unmount()
    })

    async function open(resolvePreflight = true): Promise<void> {
        if (resolvePreflight) {
            releasePreflight()
        }
        logic = firstRunEmailAgentLogic({ templateId: TEMPLATE.id })
        logic.mount()
        if (resolvePreflight) {
            await expectLogic(editor).toFinishAllListeners()
        } else {
            await expectLogic(firstRunGalleryLogic).toDispatchActions([
                'loadEmailTemplatesSuccess',
                'loadSeenEventsSuccess',
            ])
        }
    }

    it('opens PostHog AI with the selected unsaved email and sends no prompt', async () => {
        await open()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBeFalsy()
        const context = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')
        expect(context?.label).toBe('Email 1 of 2: Welcome')
        expect(JSON.parse(context?.value ?? '{}')).toMatchObject({
            template_id: 'example-sequence',
            email_id: 'email_1',
            position: 1,
            total: 2,
            email: { subject: 'Welcome', preheader: 'Preview for Welcome', text: 'Body for Welcome' },
        })

        editor.actions.openEmail('email_2')
        await expectLogic(editor).toFinishAllListeners()
        editor.actions.editEmail('email_2', {
            ...editor.values.openEmail!.email,
            subject: 'Short next step',
            text: 'Try one feature.',
        })
        const updated = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')
        expect(updated?.label).toBe('Email 2 of 2: Short next step')
        expect(JSON.parse(updated?.value ?? '{}')).toMatchObject({
            email_id: 'email_2',
            position: 2,
            total: 2,
            email: { subject: 'Short next step', text: 'Try one feature.' },
        })

        logic.unmount()
        expect(attachedContextLogic.values.contextItems).toEqual([])
    })

    it('reattaches a dismissed email when the button reopens PostHog AI', async () => {
        await open()
        const email = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')!
        attachedContextLogic.actions.dismissContext(attachedContextItemKey(email), email.dismissGroup)
        expect(attachedContextLogic.values.contextItems).toEqual([])
        logic.actions.openEmailAgent()
        expect(attachedContextLogic.values.contextItems.find((item) => item.type === 'text')?.label).toBe(
            'Email 1 of 2: Welcome'
        )
    })

    it('waits for preflight before opening and clears context when AI becomes unavailable', async () => {
        await open(false)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(attachedContextLogic.values.contextItems).toEqual([])
        releasePreflight()
        await expectLogic(preflightLogic).toFinishAllListeners()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        preflightResponse = { ...preflightResponse, cloud: false, is_debug: false, anthropic_available: false }
        preflightLogic.actions.loadPreflight()
        await expectLogic(preflightLogic).toFinishAllListeners()
        expect(attachedContextLogic.values.contextItems).toEqual([])
        expect(logic.values.aiDisabledReason).toBeTruthy()
    })

    it('removes the unsaved email context when the user switches to legacy PostHog AI', async () => {
        await open()
        maxGlobalLogic.actions.setPhaiViewMode('legacy')

        expect(attachedContextLogic.values.contextItems).toEqual([])
    })

    it('preserves another open panel until the user chooses PostHog AI', async () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)
        await open()
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
        logic.actions.openEmailAgent()
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
    })

    it('does not remember a dismissal when AI was already closed', async () => {
        await open()
        sidePanelStateLogic.actions.setSidePanelOpen(false)
        sidePanelStateLogic.actions.closeSidePanel()
        expect(sessionStorage.getItem('workflows-first-run-ai-dismissed')).toBeNull()
    })

    it('keeps a manually closed panel closed across email switches and revisits until the button reopens it', async () => {
        await open()
        sidePanelStateLogic.actions.closeSidePanel(SidePanelTab.Max)
        editor.actions.openEmail('email_2')
        await expectLogic(editor).toFinishAllListeners()
        logic.unmount()
        await open()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(attachedContextLogic.values.contextItems.find((item) => item.type === 'text')?.label).toBe(
            'Email 2 of 2: Next steps'
        )
        logic.actions.openEmailAgent()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBeFalsy()
    })

    it.each([
        {
            name: 'the AI rollout resolves',
            delay: () => featureFlagLogic.actions.setFeatureFlags([], {}),
            resolve: () =>
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
                    [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
                }),
        },
        {
            name: 'the side panel mounts',
            delay: () => sidePanelStateLogic.actions.setSidePanelAvailable(false),
            resolve: () => sidePanelStateLogic.actions.setSidePanelAvailable(true),
        },
    ])('opens after $name and preserves a later dismissal', async ({ delay, resolve }) => {
        delay()
        await open()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)

        resolve()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        sidePanelStateLogic.actions.closeSidePanel(SidePanelTab.Max)
        resolve()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it('attaches the plain text body without a visual design that will not be sent', async () => {
        await open()
        editor.actions.editEmail('email_1', {
            ...editor.values.openEmail!.email,
            html: '',
            text: 'The new plain text body.',
        })
        const email = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')!
        expect(JSON.parse(email.value!).email).toEqual({
            subject: 'Welcome',
            preheader: 'Preview for Welcome',
            text: 'The new plain text body.',
            body_mode: 'plaintext',
        })
    })

    it('uses rendered HTML when the visual design exceeds the context budget', async () => {
        await open()
        editor.actions.editEmail('email_1', {
            ...editor.values.openEmail!.email,
            text: '',
            html: '<p>The rendered email body.</p>',
            design: { body: { rows: [], values: { content: 'a'.repeat(100_000) } } },
        })
        const email = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')!
        expect(JSON.parse(email.value!)).toMatchObject({
            email: { html: '<p>The rendered email body.</p>', body_mode: 'visual' },
            omitted_content: expect.any(String),
        })
    })

    it('bounds escaped metadata and the chip label as well as oversized email bodies', async () => {
        await open()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': {
                    count: 1,
                    results: [{ ...TEMPLATE, name: '\u0000'.repeat(100_000) }],
                },
            },
        })
        firstRunGalleryLogic.actions.loadEmailTemplates()
        await expectLogic(firstRunGalleryLogic).toFinishAllListeners()
        editor.actions.editEmail('email_1', {
            ...editor.values.openEmail!.email,
            subject: '\u0000'.repeat(100_000),
            preheader: '\u0000'.repeat(100_000),
            text: '\u0000'.repeat(100_000),
            html: '<p>' + 'a'.repeat(100_000) + '</p>',
        })
        const email = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')!
        expect(email.value!.length).toBeLessThanOrEqual(64_000)
        expect(email.label!.length).toBeLessThanOrEqual(256)
        expect(JSON.parse(email.value!)).toMatchObject({
            email_id: 'email_1',
            omitted_content: expect.any(String),
        })
    })

    it('keeps oversized unsaved email context parseable and within its per-message budget', async () => {
        await open()
        editor.actions.editEmail('email_1', {
            ...editor.values.openEmail!.email,
            text: '\u0000'.repeat(100_000),
            design: { body: { rows: [], values: { content: 'a'.repeat(100_000) } } },
        })

        const context = attachedContextLogic.values.contextItems.find((item) => item.type === 'text')
        expect(context?.value?.length).toBeLessThanOrEqual(64_000)
        expect(JSON.parse(context?.value ?? '{}')).toMatchObject({
            email_id: 'email_1',
            position: 1,
            total: 2,
            omitted_content: expect.any(String),
        })
    })
})

import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { newWorkflowComposerPromptLogic } from './newWorkflowComposerPromptLogic'

const SCENE_INTEGRATION_FLAGS = [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE]
const PROMPT = 'Send a welcome email'
const SOURCE = 'cdp_destination_cross_sell'

describe('newWorkflowComposerPromptLogic', () => {
    let logic: ReturnType<typeof newWorkflowComposerPromptLogic.build>
    let seeds: ReturnType<typeof composerSeedLogic.build>
    let capture: jest.SpyInstance

    beforeEach(() => {
        useMocks(maxMocks)
    })

    function mountWith(flags: string[], approved: boolean, search: Record<string, string>): void {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        router.actions.push('/workflows/new/workflow', search, {})
        seeds = composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID })
        seeds.mount()
        logic = newWorkflowComposerPromptLogic()
        logic.mount()
    }

    afterEach(() => {
        logic?.unmount()
        seeds?.unmount()
        capture?.mockRestore()
    })

    // The prompt is URL-controlled, so it auto-submits only under the organization's AI data processing consent.
    it.each([
        { name: 'prefills and auto-submits with consent', approved: true },
        { name: 'only prefills without consent', approved: false },
    ])('consumeComposerPrompt $name', async ({ approved }) => {
        mountWith(SCENE_INTEGRATION_FLAGS, approved, { mode: 'ai', prompt: PROMPT, source: SOURCE })

        await expectLogic(logic, () => {
            logic.actions.consumeComposerPrompt()
        }).toFinishAllListeners()

        // The prompt leaves the URL so a reload cannot submit it again; the source stays to keep the composer open.
        expect(router.values.searchParams).toEqual({ mode: 'ai', source: SOURCE })
        expect(seeds.values.seed).toEqual({ prompt: PROMPT, autoSubmit: approved })
        expect(capture).toHaveBeenCalledWith('workflow ai composer prompt prefilled', {
            source: SOURCE,
            prompt_length: PROMPT.length,
            auto_submitted: approved,
        })
    })

    it('drops the prompt when the composer cannot open, but still cleans the URL', async () => {
        mountWith([], true, { mode: 'ai', prompt: PROMPT, source: SOURCE })

        await expectLogic(logic, () => {
            logic.actions.consumeComposerPrompt()
        }).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ mode: 'ai', source: SOURCE })
        expect(seeds.values.seed).toBeNull()
        expect(capture).not.toHaveBeenCalledWith('workflow ai composer prompt prefilled', expect.anything())
    })

    it('does nothing without a prompt', async () => {
        mountWith(SCENE_INTEGRATION_FLAGS, true, { mode: 'ai' })

        await expectLogic(logic, () => {
            logic.actions.consumeComposerPrompt()
        }).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ mode: 'ai' })
        expect(seeds.values.seed).toBeNull()
    })
})

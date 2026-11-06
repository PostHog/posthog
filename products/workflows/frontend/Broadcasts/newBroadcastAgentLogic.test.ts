import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

const AI_FIRST_FLAGS = [
    FEATURE_FLAGS.BROADCASTS_AI_FIRST_NEW,
    FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
    FEATURE_FLAGS.PHAI_SANDBOX_MODE,
]

describe('newBroadcastAgentLogic', () => {
    let logic: ReturnType<typeof newBroadcastAgentLogic.build>

    const setFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = newBroadcastAgentLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The flag-off path must stay on the wizard, and exposure is recorded only for a click the composer could answer.
    it.each([
        { name: 'flag on', flags: AI_FIRST_FLAGS, mode: { mode: 'ai' }, exposed: true, composer: true },
        {
            name: 'flag off',
            flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
            mode: {},
            exposed: true,
            composer: false,
        },
        {
            name: 'scene integration off',
            flags: [FEATURE_FLAGS.BROADCASTS_AI_FIRST_NEW],
            mode: {},
            exposed: false,
            composer: false,
        },
    ])('startNewBroadcast opens the composer only with $name', async ({ flags, mode, exposed, composer }) => {
        setFlags(flags)
        const recordExposure = jest.spyOn(posthog, 'getFeatureFlag').mockReturnValue(undefined)
        router.actions.push('/broadcasts')

        await expectLogic(logic, () => {
            logic.actions.startNewBroadcast()
        }).toFinishAllListeners()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/broadcasts/new')
        expect(router.values.searchParams).toEqual(mode)
        expect(logic.values.aiComposerAvailable).toBe(composer)
        if (exposed) {
            expect(recordExposure).toHaveBeenCalledWith(FEATURE_FLAGS.BROADCASTS_AI_FIRST_NEW)
        } else {
            expect(recordExposure).not.toHaveBeenCalled()
        }
    })

    it('the escape hatch opens the wizard and keeps the composer away', async () => {
        setFlags(AI_FIRST_FLAGS)
        router.actions.push('/broadcasts/new', { mode: 'ai' })
        expect(logic.values.aiComposerAvailable).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.openWizardFromAiComposer()
        }).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ mode: 'editor' })
        expect(logic.values.aiComposerAvailable).toBe(false)
    })
})

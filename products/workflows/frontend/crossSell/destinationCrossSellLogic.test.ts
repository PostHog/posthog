import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { HogFunctionTemplateWithSubTemplateType } from '~/types'

import { WORKFLOWS_CROSS_SELL_DISMISSAL_TTL_MS, suggestionsForTemplate } from './competingDestinationTemplates'
import { destinationCrossSellLogic } from './destinationCrossSellLogic'

const CATALOG_PATH = '/pipeline/new/destination'
const DESTINATION_URL = '/functions/new/template-customerio'
const SCENE_INTEGRATION_FLAGS = [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE]
const SUGGESTION = suggestionsForTemplate('template-customerio')[1]

function template(
    overrides: Partial<HogFunctionTemplateWithSubTemplateType> = {}
): HogFunctionTemplateWithSubTemplateType {
    return {
        id: 'template-customerio',
        name: 'Customer.io',
        type: 'destination',
        status: 'stable',
        ...overrides,
    } as HogFunctionTemplateWithSubTemplateType
}

describe('destinationCrossSellLogic', () => {
    let logic: ReturnType<typeof destinationCrossSellLogic.build>
    let capture: jest.SpyInstance
    let recordIntent: jest.SpyInstance

    const setFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    beforeEach(() => {
        // `dismissedAt` is persisted to localStorage, which jsdom keeps between tests.
        localStorage.clear()
        useMocks(maxMocks)
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        recordIntent = jest.spyOn(api.productIntents, 'update').mockResolvedValue(MOCK_DEFAULT_TEAM)
        router.actions.push(CATALOG_PATH, {}, {})
        logic = destinationCrossSellLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        capture.mockRestore()
        recordIntent.mockRestore()
    })

    // The offer is only right for a real competing destination; the same list renders alert sub-templates too.
    it.each([
        {
            name: 'a competing destination',
            flags: [FEATURE_FLAGS.CDP_WORKFLOWS_CROSS_SELL],
            overrides: {},
            expected: true,
        },
        { name: 'a competing destination with the flag off', flags: [], overrides: {}, expected: false },
        {
            name: 'a destination that does not compete',
            flags: [FEATURE_FLAGS.CDP_WORKFLOWS_CROSS_SELL],
            overrides: { id: 'template-slack', name: 'Slack' },
            expected: false,
        },
        {
            name: 'an alert sub-template',
            flags: [FEATURE_FLAGS.CDP_WORKFLOWS_CROSS_SELL],
            overrides: { type: 'internal_destination', sub_template_id: 'error-tracking-issue-created' },
            expected: false,
        },
        {
            name: 'a hidden template',
            flags: [FEATURE_FLAGS.CDP_WORKFLOWS_CROSS_SELL],
            overrides: { status: 'hidden' },
            expected: false,
        },
    ] as {
        name: string
        flags: string[]
        overrides: Partial<HogFunctionTemplateWithSubTemplateType>
        expected: boolean
    }[])('shouldIntercept is $expected for $name', ({ flags, overrides, expected }) => {
        setFlags(flags)

        expect(logic.values.shouldIntercept(template(overrides))).toBe(expected)
    })

    it('stays quiet for 30 days after a dismissal, and the dismissal survives a reload', async () => {
        setFlags([FEATURE_FLAGS.CDP_WORKFLOWS_CROSS_SELL])
        const now = jest.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000)

        await expectLogic(logic, () => {
            logic.actions.openModal(template(), DESTINATION_URL)
            logic.actions.closeModal()
        }).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(false)
        expect(logic.values.shouldIntercept(template())).toBe(false)
        expect(capture).toHaveBeenCalledWith('workflows cross-sell modal dismissed', {
            template_id: 'template-customerio',
            template_name: 'Customer.io',
            reason: 'closed',
            step: 'intro',
        })

        now.mockReturnValue(1_700_000_000_000 + WORKFLOWS_CROSS_SELL_DISMISSAL_TTL_MS + 1)
        expect(logic.values.shouldIntercept(template())).toBe(true)

        logic.unmount()
        logic = destinationCrossSellLogic()
        logic.mount()
        expect(logic.values.dismissedAt).toBe(1_700_000_000_000)

        now.mockRestore()
    })

    it('continueWithDestination sends the person where the click was going', async () => {
        await expectLogic(logic, () => {
            logic.actions.openModal(template(), DESTINATION_URL)
            logic.actions.continueWithDestination()
        }).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(false)
        expect(logic.values.dismissedAt).not.toBeNull()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(DESTINATION_URL)
        expect(capture).toHaveBeenCalledWith(
            'workflows cross-sell modal dismissed',
            expect.objectContaining({ reason: 'continue_with_destination' })
        )
    })

    // The describe step only exists where the composer can answer it; elsewhere the editor is the next best place.
    it.each([
        {
            name: 'goes to the describe step when the composer is available',
            flags: SCENE_INTEGRATION_FLAGS,
            describe: true,
        },
        { name: 'opens the editor when the composer is unavailable', flags: [], describe: false },
    ])('tryWorkflows $name', async ({ flags, describe: expectDescribe }) => {
        setFlags(flags)

        await expectLogic(logic, () => {
            logic.actions.openModal(template(), DESTINATION_URL)
            logic.actions.tryWorkflows()
        }).toFinishAllListeners()

        expect(recordIntent).toHaveBeenCalledWith({
            product_type: 'workflows',
            intent_context: 'workflows_cross_sell_from_destination',
            metadata: {
                template_id: 'template-customerio',
                from: 'pipeline_destinations',
                to: 'workflows',
                type: 'cross_sell',
            },
        })
        expect(capture).toHaveBeenCalledWith('workflows cross-sell accepted', {
            template_id: 'template-customerio',
            template_name: 'Customer.io',
            ai_composer_available: expectDescribe,
        })
        expect(logic.values.dismissedAt).not.toBeNull()
        if (expectDescribe) {
            expect(logic.values.isOpen).toBe(true)
            expect(logic.values.step).toBe('describe')
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(CATALOG_PATH)
        } else {
            expect(logic.values.isOpen).toBe(false)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/workflows/new/workflow')
            expect(router.values.searchParams).toEqual({})
        }
    })

    it.each([
        { name: 'a typed prompt', useSuggestion: false },
        { name: 'a suggestion', useSuggestion: true },
    ])('submitPrompt hands $name to the composer with the source', async ({ useSuggestion }) => {
        setFlags(SCENE_INTEGRATION_FLAGS)

        await expectLogic(logic, () => {
            logic.actions.openModal(template(), DESTINATION_URL)
            logic.actions.tryWorkflows()
            if (useSuggestion) {
                logic.actions.selectSuggestion(SUGGESTION, 1)
            } else {
                logic.actions.setPrompt('  Send a welcome email  ')
            }
            logic.actions.submitPrompt()
        }).toFinishAllListeners()

        const prompt = useSuggestion ? SUGGESTION.prompt : 'Send a welcome email'
        expect(logic.values.isOpen).toBe(false)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/workflows/new/workflow')
        expect(router.values.searchParams).toEqual({ mode: 'ai', prompt, source: 'cdp_destination_cross_sell' })
        expect(capture).toHaveBeenCalledWith('workflows cross-sell prompt submitted', {
            template_id: 'template-customerio',
            template_name: 'Customer.io',
            prompt_length: prompt.length,
            used_suggestion: useSuggestion,
        })
    })

    it('submitPrompt does nothing without a prompt', async () => {
        setFlags(SCENE_INTEGRATION_FLAGS)

        await expectLogic(logic, () => {
            logic.actions.openModal(template(), DESTINATION_URL)
            logic.actions.tryWorkflows()
            logic.actions.setPrompt('   ')
            logic.actions.submitPrompt()
        }).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(true)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(CATALOG_PATH)
    })
})

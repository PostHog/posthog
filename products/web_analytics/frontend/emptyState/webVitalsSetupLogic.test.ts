import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

import { webVitalsSetupLogic } from './webVitalsSetupLogic'

jest.mock('products/event_definitions/frontend/generated/api', () => ({ eventDefinitionsList: jest.fn() }))

describe('webVitalsSetupLogic', () => {
    // Guards the three-state mapping the web vitals gate hangs off: dropping the
    // opt-in branch would show "enable autocapture" to already-enabled projects,
    // and existing vitals must outrank the toggle.
    it.each([
        [true, false, 'has-data'],
        [true, true, 'has-data'],
        [false, true, 'waiting-for-data'],
        [false, false, 'needs-setup'],
    ])('definition=%s, optIn=%s maps to %s', async (hasDefinition, optIn, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_web_vitals_opt_in: optIn } as TeamType)
        ;(eventDefinitionsList as jest.Mock).mockResolvedValue({
            results: hasDefinition ? [{ name: '$web_vitals' }] : [],
        })
        webVitalsSetupLogic.mount()
        await expectLogic(webVitalsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.WEB_ANALYTICS }).values.status).toBe(expected)
    })
})

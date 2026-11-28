import { render } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AdventEntry } from './AdventEntry'

describe('AdventEntry', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    it.each([
        ['hides the card while the flag is off', false, false],
        ['shows the card while the flag is on', true, true],
    ])('%s', (_, flagOn, shown) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: flagOn })

        const { container } = render(<AdventEntry />)

        expect(container.querySelector('[data-attr="advent-entry-card"]') !== null).toBe(shown)
    })
})

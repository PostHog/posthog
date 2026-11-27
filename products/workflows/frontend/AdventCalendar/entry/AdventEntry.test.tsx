import { render } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AdventEntry } from './AdventEntry'

describe('AdventEntry', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    it.each([
        ['hides the card while the flag is off', false, urls.workflows(), false],
        ['shows the card on Workflows', true, urls.workflows(), true],
        ['shows the card on Broadcasts', true, urls.broadcasts(), true],
        ['shows the card on Transactional', true, urls.transactional(), true],
        ['hides the card on the calendar itself', true, urls.workflowsAdventCalendar(), false],
    ])('%s', (_, flagOn, path, shown) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: flagOn })
        router.actions.push(path)

        const { container } = render(<AdventEntry />)

        const href = container.querySelector('[data-attr="advent-entry-card-open"]')?.getAttribute('href')
        expect(href?.includes(urls.workflowsAdventCalendar()) ?? false).toBe(shown)
    })
})

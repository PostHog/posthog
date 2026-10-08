import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AudienceScene } from './AudienceScene'

jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: ({ name }: { name: string }) => <h1>{name}</h1>,
}))
jest.mock('lib/components/NotFound', () => ({
    NotFound: () => <div data-attr="page-not-found" />,
}))
jest.mock('../EmailSuspensionBanner', () => ({ EmailSuspensionBanner: () => null }))
jest.mock('../OptOuts/NewCategoryButton', () => ({ NewCategoryButton: () => null }))
jest.mock('../OptOuts/OptOutScene', () => ({ OptOutScene: () => null }))
jest.mock('../Suppression/SuppressionScene', () => ({ SuppressionScene: () => null }))

describe('AudienceScene', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { flag: true, notFoundShown: false },
        { flag: false, notFoundShown: true },
    ])('with workflows-audience $flag, not found shown is $notFoundShown', ({ flag, notFoundShown }) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: flag })

        render(
            <Provider>
                <AudienceScene />
            </Provider>
        )

        expect(!!document.querySelector('[data-attr="page-not-found"]')).toBe(notFoundShown)
        expect(!!screen.queryByText('Suppression list')).toBe(!notFoundShown)
    })
})

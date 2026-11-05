import { cleanup, render } from '@testing-library/react'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'

import { SetupInstallOptions } from './SetupInstallOptions'

jest.mock('lib/api')

describe('SetupInstallOptions', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { realm: 'cloud', cloud: true, showsWizard: true },
        { realm: 'hosted-clickhouse', cloud: false, showsWizard: false },
    ])('on $realm shows the Wizard command: $showsWizard', ({ realm, cloud, showsWizard }) => {
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ cloud, realm, is_debug: false } as any)

        const { container } = render(<SetupInstallOptions />)

        expect(container.textContent?.includes('@posthog/wizard')).toBe(showsWizard)
    })
})

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Component, ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CustomCategorySuffix } from '~/layout/panel-layout/ProjectTree/CustomCategorySuffix'
import { ProductItemCategory } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AdventClassicNavTreeButton } from './AdventClassicNavTreeButton'

jest.mock('products/workflows/frontend/AdventCalendar/entry/AdventNavTreeButton', () => {
    throw new TypeError('Failed to fetch dynamically imported module: /static/AdventNavTreeButton.js')
})
jest.mock('products/workflows/frontend/AdventCalendar/entry/adventHoverSnow', () => {
    throw new TypeError('Failed to fetch dynamically imported module: /static/adventHoverSnow.js')
})

class AppErrorScreen extends Component<{ children: ReactNode }, { failed: boolean }> {
    override state = { failed: false }

    static getDerivedStateFromError(): { failed: boolean } {
        return { failed: true }
    }

    override render(): ReactNode {
        return this.state.failed ? 'PostHog could not load' : this.props.children
    }
}

async function runPendingWork(): Promise<void> {
    await act(() => jest.runAllTimersAsync())
}

describe('the sidebar when the advent chunks fail to load', () => {
    let unhandledRejections: unknown[]
    const recordRejection = (reason: unknown): void => {
        unhandledRejections.push(reason)
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.spyOn(console, 'error').mockImplementation(() => {})
        jest.spyOn(window, 'matchMedia').mockImplementation(
            (query: string) => ({ matches: false, media: query }) as MediaQueryList
        )
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: true })
        unhandledRejections = []
        process.on('unhandledRejection', recordRejection)
    })

    afterEach(() => {
        cleanup()
        process.off('unhandledRejection', recordRejection)
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('keeps the Messaging header and omits the tree when the tree chunk fails', async () => {
        render(
            <AppErrorScreen>
                Messaging
                <CustomCategorySuffix category={ProductItemCategory.MESSAGING} nav="classic" />
            </AppErrorScreen>
        )
        await runPendingWork()

        expect(screen.queryByText('PostHog could not load')).toBeNull()
        expect(screen.getByText('Messaging')).toBeTruthy()
        expect(screen.queryByLabelText('Open the Workflows advent calendar')).toBeNull()
    })

    it('rejects nothing unhandled when the snow chunk fails while the pointer is on the tree', async () => {
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        render(<AdventClassicNavTreeButton />)
        const tree = screen.getByLabelText('Open the Workflows advent calendar')

        await user.hover(tree)
        await user.unhover(tree)
        await runPendingWork()
        await new Promise((resolve) => jest.requireActual('timers').setImmediate(resolve))

        expect(unhandledRejections).toEqual([])
    })
})

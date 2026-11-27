import { act, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventShareModal } from './AdventShareModal'

describe('AdventShareModal', () => {
    let clipboard: string | null
    let capture: jest.SpyInstance

    beforeEach(() => {
        clipboard = null
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: async (text: string) => {
                    clipboard = text
                },
            },
        })
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        initKeaTests()
        adventCalendarLogic.mount()
    })

    afterEach(() => {
        capture.mockRestore()
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    })

    const sharedLink = (dataAttr: string, param: string): string | null => {
        const href = document.querySelector(`[data-attr="${dataAttr}"]`)?.getAttribute('href')
        return href ? new URL(href).searchParams.get(param) : null
    }

    it('shares a link that opens the calendar of whoever follows it', async () => {
        render(<AdventShareModal isOpen onClose={() => {}} />)
        await act(async () => screen.getByText('Copy link').click())

        const links = [sharedLink('advent-share-linkedin', 'url'), sharedLink('advent-share-x', 'url'), clipboard]

        for (const link of links) {
            const url = new URL(link ?? '')
            expect({ origin: url.origin, pathname: url.pathname, search: url.search }).toEqual({
                origin: 'https://app.posthog.com',
                pathname: '/workflows/advent',
                search: '',
            })
        }
    })
})

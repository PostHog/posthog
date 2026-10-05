import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { recipientsLogic } from './recipientsLogic'
import { MockResponse, useRecipientsApiMocks } from './recipientTestFixtures'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

function auxClick(button: number): MouseEvent {
    return new MouseEvent('auxclick', { bubbles: true, cancelable: true, button })
}

describe('UnreachablePersonsNotice', () => {
    function useCoverageResponse(response: MockResponse): void {
        useRecipientsApiMocks({ recipients: () => [200, { results: [], next_cursor: null }], coverage: response })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('opens the filtered persons list', async () => {
        useCoverageResponse([200, { persons_without_email: 1342 }])
        render(<UnreachablePersonsNotice />)

        fireEvent.click(await screen.findByText("1,342 persons can't be reached"))

        expect(router.values.location.pathname).toContain(urls.persons())
    })

    it.each([
        { name: 'a click', open: (link: HTMLElement) => fireEvent.click(link), expected: 1 },
        { name: 'a Cmd-click', open: (link: HTMLElement) => fireEvent.click(link, { metaKey: true }), expected: 1 },
        { name: 'a Ctrl-click', open: (link: HTMLElement) => fireEvent.click(link, { ctrlKey: true }), expected: 1 },
        { name: 'a middle click', open: (link: HTMLElement) => fireEvent(link, auxClick(1)), expected: 1 },
        { name: 'a right click', open: (link: HTMLElement) => fireEvent(link, auxClick(2)), expected: 0 },
    ])('tracks how many persons it shows once on $name', async ({ open, expected }) => {
        useCoverageResponse([200, { persons_without_email: 1342 }])
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        render(<UnreachablePersonsNotice />)

        open(await screen.findByText("1,342 persons can't be reached"))

        const opened = capture.mock.calls.filter(([event]) => event === 'audience unreachable persons opened')
        expect(opened).toEqual(Array(expected).fill(['audience unreachable persons opened', { count: 1342 }]))
    })

    it.each([
        {
            name: 'every person has an email property',
            response: [200, { persons_without_email: 0 }],
            action: 'loadAudienceCoverageSuccess',
        },
        {
            name: 'the count fails to load',
            response: [500, { detail: 'Query timed out' }],
            action: 'loadAudienceCoverageFailure',
        },
    ] as const)('stays hidden without a toast when $name', async ({ response, action }) => {
        useCoverageResponse([response[0], response[1]])
        const toastError = jest.spyOn(lemonToast, 'error')
        const { container } = render(<UnreachablePersonsNotice />)

        await expectLogic(recipientsLogic).toDispatchActions([action])

        expect(container).toBeEmptyDOMElement()
        expect(toastError).not.toHaveBeenCalled()
    })
})

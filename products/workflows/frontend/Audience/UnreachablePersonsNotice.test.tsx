import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { recipientsLogic } from './recipientsLogic'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

describe('UnreachablePersonsNotice', () => {
    function useCoverageResponse(response: [number, unknown]): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': { results: [], next_cursor: null },
                '/api/projects/:team_id/messaging_recipients/coverage/': () => response,
            },
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('opens the filtered persons list and tracks how many persons it shows', async () => {
        useCoverageResponse([200, { persons_without_email: 1342 }])
        const capture = jest.spyOn(posthog, 'capture')
        render(<UnreachablePersonsNotice />)

        fireEvent.click(await screen.findByText("1,342 persons can't be reached"))

        expect(capture).toHaveBeenCalledWith('audience unreachable persons opened', { count: 1342 })
        expect(router.values.location.pathname).toContain(urls.persons())
        expect(router.values.hashParams.q.source.properties).toEqual([
            { type: 'person', key: 'email', operator: 'not_regex', value: '[^ \\t\\n\\r]' },
        ])
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

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { recipientsLogic } from './recipientsLogic'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

describe('UnreachablePersonsNotice', () => {
    function usePersonsWithoutEmail(count: number): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': { results: [], next_cursor: null },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: count },
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
        usePersonsWithoutEmail(1342)
        const capture = jest.spyOn(posthog, 'capture')
        render(<UnreachablePersonsNotice />)

        fireEvent.click(await screen.findByText("1,342 persons can't be reached"))

        expect(capture).toHaveBeenCalledWith('audience unreachable persons opened', { count: 1342 })
        expect(router.values.location.pathname).toContain(urls.persons())
        expect(router.values.hashParams.q.source.properties).toEqual([
            { type: 'person', key: 'email', operator: 'not_regex', value: '[^ \\t\\n\\r]' },
        ])
    })

    it('stays hidden when every person has an email property', async () => {
        usePersonsWithoutEmail(0)
        const { container } = render(<UnreachablePersonsNotice />)

        await expectLogic(recipientsLogic).toDispatchActions(['loadAudienceCoverageSuccess'])

        expect(container).toBeEmptyDOMElement()
    })
})

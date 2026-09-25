import '@testing-library/jest-dom'

import { act, cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FIXTURE_TEMPLATES, FIXTURE_WORKFLOWS, paginated } from './Workflows/WorkflowsListV2/workflowsListV2Fixtures'
import { WorkflowsScene } from './WorkflowsScene'

const shownRowNames = (): string[] =>
    Array.from(document.querySelectorAll('[data-attr="workflows-list-v2-name"]')).map((el) => el.textContent ?? '')

describe('WorkflowsScene', () => {
    let summariesRequests: string[]

    beforeEach(() => {
        summariesRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => {
                    summariesRequests.push(request.url)
                    return [200, paginated(FIXTURE_WORKFLOWS)]
                },
                '/api/projects/:team_id/messaging_templates/summaries/': ({ request }) => {
                    summariesRequests.push(request.url)
                    return [200, paginated(FIXTURE_TEMPLATES)]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.workflows())
    })

    afterEach(() => cleanup())

    it('filters the list to active workflows from the keyboard and writes the pills to the URL', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        const user = userEvent.setup()
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(shownRowNames()).toContain('Welcome series'))
        expect(shownRowNames()).toContain('Receipt')

        const input = document.querySelector<HTMLInputElement>('input[data-attr="workflows-search"]')
        expect(input).not.toBeNull()
        await user.click(input!)
        await user.keyboard('sta')
        await user.keyboard('{Tab}')
        expect(input).toHaveValue('status:')
        await user.keyboard('{ArrowDown}{Enter}')

        await waitFor(() => expect(shownRowNames()).toEqual(['Welcome series']))
        expect(router.values.searchParams.q).toEqual('status:active')
        expect(input).toHaveValue('')
    })

    it('keeps the old list when the flag is off and never asks for summaries', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <Provider>
                <WorkflowsScene />
            </Provider>
        )

        await waitFor(() => expect(document.querySelector('[data-attr="workflows-table"]')).not.toBeNull())
        expect(document.querySelector('input[data-attr="workflows-search"]')).toBeNull()
        await act(async () => {})
        expect(summariesRequests).toEqual([])
    })
})

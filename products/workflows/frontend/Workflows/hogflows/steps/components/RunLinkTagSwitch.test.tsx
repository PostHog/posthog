import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { RunLinkTagSwitch } from './RunLinkTagSwitch'

describe('<RunLinkTagSwitch />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { project: undefined, checked: true, shownOn: true, turnedTo: [false] },
        { project: true, checked: false, shownOn: false, turnedTo: [true] },
        { project: false, checked: true, shownOn: false, turnedTo: [] },
    ])(
        'with the project setting $project and the email at $checked, shows on=$shownOn and turns to $turnedTo',
        ({ project, checked, shownOn, turnedTo }) => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                workflows_config: {
                    capture_workflows_engagement_events: true,
                    ...(project === undefined ? {} : { email_workflow_run_link_tag_enabled: project }),
                },
            })
            const changes: boolean[] = []

            const { container } = render(
                <RunLinkTagSwitch
                    checked={checked}
                    onChange={(value) => changes.push(value)}
                    data-attr="workflow-email-run-link-tag-toggle"
                />
            )
            const toggle = container.querySelector('[data-attr="workflow-email-run-link-tag-toggle"]') as HTMLElement
            fireEvent.click(toggle)

            expect(toggle).toHaveAttribute('aria-checked', String(shownOn))
            expect(changes).toEqual(turnedTo)
        }
    )
})

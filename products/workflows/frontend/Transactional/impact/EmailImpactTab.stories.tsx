import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'
import { EmailImpactTab } from './EmailImpactTab'

const WORKFLOW_ID = '0190a1b2-0000-7000-8000-0000000000f1'

const tracked: TransactionalEmailImpactApi = {
    sent: 4200,
    delivered: 4130,
    opened: 2380,
    clicked: 610,
    not_clicked: 3540,
    untracked: 0,
    clicks_untracked: 0,
    window_days: 7,
    after_click: null,
    without_click: null,
}

const someUntracked: TransactionalEmailImpactApi = { ...tracked, untracked: 1200 }

const meta: Meta = {
    title: 'Products/Workflows/EmailImpactTab',
    component: EmailImpactTab,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { waitForSelector: '[data-attr="email-impact-funnel"]', snapshotBrowsers: [] },
    },
}
export default meta

const Template: StoryFn<{ impact: TransactionalEmailImpactApi; event: string | null; replay?: boolean }> = ({
    impact,
    event,
    replay = true,
}) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/transactional_email_log/impact/': ({ request }: { request: Request }) => {
                if (!new URL(request.url).searchParams.get('event')) {
                    return [200, impact]
                }
                return [
                    200,
                    {
                        ...impact,
                        after_click: impact.clicked ? { sends: 580, converted: 131 } : { sends: 0, converted: 0 },
                        without_click: { sends: 3300, converted: 72 },
                    },
                ]
            },
        },
    })
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const { setEvent } = useActions(emailImpactLogic({ workflowId: WORKFLOW_ID }))
    const [ready, setReady] = useState(false)
    useLayoutEffect(() => {
        loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay })
        setEvent(event)
        setReady(true)
    }, [loadCurrentTeamSuccess, setEvent, event, replay])

    return ready ? <EmailImpactTab workflowId={WORKFLOW_ID} /> : <></>
}

export const WithConversionEvent = Template.bind({})
WithConversionEvent.args = { impact: tracked, event: 'plan upgraded' }

export const NoConversionEvent = Template.bind({})
NoConversionEvent.args = { impact: tracked, event: null }

export const SomeSendsUntracked = Template.bind({})
SomeSendsUntracked.args = { impact: someUntracked, event: 'plan upgraded' }

export const NoSessionReplay = Template.bind({})
NoSessionReplay.args = { impact: tracked, event: 'plan upgraded', replay: false }

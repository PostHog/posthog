import { Meta, StoryFn } from '@storybook/react'

import type { TransactionalEmailClickSessionApi } from 'products/messaging/frontend/generated/api.schemas'

import { EmailOutcomeRow } from './emailClicks'
import { TransactionalEmailClickTimeline } from './TransactionalEmailClickTimeline'

const meta: Meta<typeof TransactionalEmailClickTimeline> = {
    title: 'Scenes-App/Transactional/Email click timeline',
    component: TransactionalEmailClickTimeline,
    parameters: { mockDate: '2026-06-15', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const DELIVERED: EmailOutcomeRow = { kind: 'delivered', key: 'delivered', at: '2026-06-15T09:00:02Z', eventUuid: 'e1' }
const OPENED: EmailOutcomeRow = { kind: 'opened', key: 'opened', at: '2026-06-15T09:01:00Z', eventUuid: 'e2' }

const SESSION: TransactionalEmailClickSessionApi = {
    session_id: 'session-1',
    landed_at: '2026-06-15T09:05:10Z',
    landing_url: 'https://app.example.com/billing?ph_workflow_run=msg-1',
    duration_seconds: 250,
    pageview_count: 3,
    device_type: 'Desktop',
    browser: 'Chrome',
    city: 'Berlin',
}

function click(
    key: string,
    at: string,
    link: string | null,
    session: TransactionalEmailClickSessionApi | null,
    noSessionReason: Extract<EmailOutcomeRow, { kind: 'click' }>['noSessionReason'] = null
): EmailOutcomeRow {
    return { kind: 'click', key, at, eventUuid: link ? `${key}-event` : null, link, session, noSessionReason }
}

const Template: StoryFn<typeof TransactionalEmailClickTimeline> = (props) => (
    <div className="max-w-180">
        <TransactionalEmailClickTimeline {...props} />
    </div>
)

export const ClicksWithSessions = Template.bind({})
ClicksWithSessions.args = {
    rows: [
        DELIVERED,
        OPENED,
        click('c1', '2026-06-15T09:05:00Z', 'https://app.example.com/billing', SESSION),
        click('c2', '2026-06-15T09:20:00Z', 'https://app.example.com/docs/setup', {
            ...SESSION,
            session_id: 'session-2',
            landed_at: '2026-06-15T09:20:04Z',
            landing_url: 'https://app.example.com/docs/setup?ph_workflow_run=msg-1',
            device_type: 'Mobile',
            browser: 'Safari',
            duration_seconds: null,
            pageview_count: null,
        }),
    ],
    failed: false,
    clickTracking: true,
}

export const ClicksWithoutSessions = Template.bind({})
ClicksWithoutSessions.args = {
    rows: [
        DELIVERED,
        OPENED,
        click('c1', '2026-06-15T09:05:00Z', 'https://help.other-site.com/faq', null, 'off_site'),
        click('c2', '2026-06-15T09:07:00Z', 'https://app.example.com/billing', null, 'not_found'),
    ],
    failed: false,
    clickTracking: true,
}

export const EngagementEventsOff = Template.bind({})
EngagementEventsOff.args = {
    rows: [DELIVERED, click('c1', '2026-06-15T09:05:00Z', null, null, 'link_unknown')],
    failed: false,
    clickTracking: true,
}

export const NoClicksYet = Template.bind({})
NoClicksYet.args = { rows: [DELIVERED, OPENED], failed: false, clickTracking: true }

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WorkflowSendingLimitsApi } from 'products/workflows/frontend/generated/api.schemas'

import { SendingLimitsBanner } from './SendingLimitsBanner'
import { workflowsSendingLimitsLogic } from './workflowsSendingLimitsLogic'

const nothingLimited: WorkflowSendingLimitsApi = {
    email_quota_limited: false,
    destination_quota_limited: false,
    email_daily_cap_reached: false,
    emails_per_day: null,
}

const sendingLimitsEndpoint = '/api/projects/:team_id/hog_flows/sending_limits/'

const sendingAllowanceUrl = '/broadcasts/reputation'

const renderBanner = ({ withAllowanceLink = true }: { withAllowanceLink?: boolean } = {}): void => {
    initKeaTests()
    render(<SendingLimitsBanner sendingAllowanceUrl={withAllowanceLink ? sendingAllowanceUrl : undefined} />)
}

describe('SendingLimitsBanner', () => {
    afterEach(() => {
        cleanup()
    })

    it('stays empty while nothing limits sending', async () => {
        useMocks({ get: { [sendingLimitsEndpoint]: nothingLimited } })
        renderBanner()

        await waitFor(() => expect(workflowsSendingLimitsLogic.values.sendingLimits).toEqual(nothingLimited))
        expect(screen.queryByTestId('workflows-email-quota-limited-banner')).toBeNull()
        expect(screen.queryByTestId('workflows-destination-quota-limited-banner')).toBeNull()
        expect(screen.queryByTestId('workflows-email-daily-cap-banner')).toBeNull()
    })

    it.each([
        {
            name: 'the email quota',
            limits: { ...nothingLimited, email_quota_limited: true },
            banner: 'workflows-email-quota-limited-banner',
            text: 'Workflows and broadcasts that send email do not run',
            link: 'Manage billing',
            href: '/organization/billing?products=workflows_emails',
        },
        {
            name: 'the destination quota',
            limits: { ...nothingLimited, destination_quota_limited: true },
            banner: 'workflows-destination-quota-limited-banner',
            text: 'Workflows with a destination or push step do not run',
            link: 'Manage billing',
            href: '/organization/billing?products=workflows_emails',
        },
        {
            name: 'the daily email cap',
            limits: { ...nothingLimited, email_daily_cap_reached: true, emails_per_day: 1000 },
            banner: 'workflows-email-daily-cap-banner',
            text: 'daily sending allowance of 1,000 emails in the last 24 hours',
            link: 'View sending allowance',
            href: sendingAllowanceUrl,
        },
    ])('explains $name and points to the next step', async ({ limits, banner, text, link, href }) => {
        useMocks({ get: { [sendingLimitsEndpoint]: limits } })
        renderBanner()

        const notice = await screen.findByTestId(banner)
        expect(notice).toHaveTextContent(text)
        // The banner renders its action twice, once per container-query layout.
        expect(within(notice).getAllByText(link)[0].closest('a')).toHaveAttribute('href', expect.stringContaining(href))
    })

    it('leaves out the daily cap while the email quota already stops email', async () => {
        useMocks({
            get: {
                [sendingLimitsEndpoint]: {
                    ...nothingLimited,
                    email_quota_limited: true,
                    email_daily_cap_reached: true,
                    emails_per_day: 1000,
                },
            },
        })
        renderBanner()

        await screen.findByTestId('workflows-email-quota-limited-banner')
        expect(screen.queryByTestId('workflows-email-daily-cap-banner')).toBeNull()
    })

    it('drops the allowance link where the allowance is already on screen', async () => {
        useMocks({ get: { [sendingLimitsEndpoint]: { ...nothingLimited, email_daily_cap_reached: true } } })
        renderBanner({ withAllowanceLink: false })

        const notice = await screen.findByTestId('workflows-email-daily-cap-banner')
        expect(within(notice).queryByText('View sending allowance')).toBeNull()
    })
})

import { render, screen, within } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { logsAlertsDestinationsList } from 'products/logs/frontend/generated/api'
import { LogsAlertDestinationConfigApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertNotificationLogic } from '../logsAlertNotificationLogic'
import { LogsAlertNotifications } from '../LogsAlertNotifications'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsDestinationsList: jest.fn(),
    logsAlertsDestinationsCreate: jest.fn(),
    logsAlertsDestinationsDeleteCreate: jest.fn(),
}))

const mockList = logsAlertsDestinationsList as jest.MockedFunction<typeof logsAlertsDestinationsList>

function onePage(results: LogsAlertDestinationConfigApi[]): ReturnType<typeof logsAlertsDestinationsList> {
    return Promise.resolve({ count: results.length, next: null, previous: null, results })
}

function renderNotifications(): void {
    render(
        <BindLogic logic={logsAlertNotificationLogic} props={{ alertId: 'alert-1' }}>
            <LogsAlertNotifications alertId="alert-1" />
        </BindLogic>
    )
}

describe('LogsAlertNotifications', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it("lists the alert's destinations", async () => {
        mockList.mockReturnValue(
            onePage([
                {
                    hog_function_ids: ['hf-1', 'hf-2'],
                    type: 'webhook',
                    enabled: true,
                    webhook_url: 'https://one.example.com/…',
                },
            ])
        )

        renderNotifications()

        expect(await screen.findByText('Webhook https://one.example.com/…')).toBeTruthy()
    })

    it('lists two destinations of the same type as two entries', async () => {
        mockList.mockReturnValue(
            onePage([
                {
                    hog_function_ids: ['hf-1', 'hf-2'],
                    type: 'webhook',
                    enabled: true,
                    webhook_url: 'https://one.example.com/…',
                },
                {
                    hog_function_ids: ['hf-3', 'hf-4'],
                    type: 'webhook',
                    enabled: true,
                    webhook_url: 'https://two.example.com/…',
                },
            ])
        )

        renderNotifications()

        expect(await screen.findByText('Webhook https://one.example.com/…')).toBeTruthy()
        expect(screen.getByText('Webhook https://two.example.com/…')).toBeTruthy()
    })

    it('tags each destination Active or Paused from its enabled flag', async () => {
        mockList.mockReturnValue(
            onePage([
                {
                    hog_function_ids: ['hf-1', 'hf-2'],
                    type: 'webhook',
                    enabled: true,
                    webhook_url: 'https://active.example.com/…',
                },
                {
                    hog_function_ids: ['hf-3', 'hf-4'],
                    type: 'teams',
                    enabled: false,
                    webhook_url: 'https://paused.example.com/…',
                },
            ])
        )

        renderNotifications()

        const activeRow = (await screen.findByText('Webhook https://active.example.com/…')).closest('div')!
        const pausedRow = screen.getByText('Microsoft Teams https://paused.example.com/…').closest('div')!

        expect(within(activeRow).getByText('Active')).toBeTruthy()
        expect(within(pausedRow).getByText('Paused')).toBeTruthy()
    })
})

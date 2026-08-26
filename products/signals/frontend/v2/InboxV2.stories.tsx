import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { InboxScoutsTab } from './components/InboxScoutsTab'
import { InboxSettingsTab } from './components/InboxSettingsTab'
import { V2FocusScene } from './V2FocusScene'
import { v2InboxLogic } from './v2InboxLogic'
import { V2InboxScene } from './V2InboxScene'
import { V2MonitorScene } from './V2MonitorScene'
import { V2ReportScene } from './V2ReportScene'
import { V2ResolvedScene } from './V2ResolvedScene'

// Mock-data redesign preview of the inbox. Every scene renders straight from
// products/signals/frontend/v2/mockData.ts, so no API mocks are needed.

// These stories render scenes outside the app shell, which is what normally hosts the toasts
function ToastHost(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    return (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox v2',
    decorators: [
        (Story) => (
            <>
                <Story />
                <ToastHost />
            </>
        ),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

export const Inbox: Story = { render: () => <V2InboxScene /> }

function ListInbox(): JSX.Element {
    const { setLayout } = useActions(v2InboxLogic)
    useEffect(() => setLayout('list'), [setLayout])
    return <V2InboxScene />
}

export const InboxList: Story = { render: () => <ListInbox /> }

export const InboxScouts: Story = {
    render: () => (
        <div className="mx-auto max-w-4xl p-4">
            <InboxScoutsTab />
        </div>
    ),
}

export const InboxSettings: Story = {
    render: () => (
        <div className="mx-auto max-w-4xl p-4">
            <InboxSettingsTab />
        </div>
    ),
}

export const FocusMode: Story = {
    render: () => (
        <div className="h-screen">
            <V2FocusScene />
        </div>
    ),
}

export const Report: Story = { render: () => <V2ReportScene id="RPT-1042" /> }

export const ReportDisputed: Story = { render: () => <V2ReportScene id="RPT-1023" /> }

export const ReportWithScreenshot: Story = { render: () => <V2ReportScene id="RPT-1031" /> }

export const ReportResolved: Story = { render: () => <V2ReportScene id="RPT-1019" /> }

export const Resolved: Story = { render: () => <V2ResolvedScene id="RPT-1019" /> }

export const Monitor: Story = { render: () => <V2MonitorScene id="RPT-1028" /> }

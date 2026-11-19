import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { MessageChannels } from '../MessageChannels'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { addEmailSenderLogic } from './addEmailSenderLogic'

interface AddSenderArgs {
    domain: string | null
}

function ChannelsWithAddSender({ domain }: AddSenderArgs): JSX.Element {
    const backend = useMemo(() => {
        const seeded = new FakeEmailDomainBackend()
        seeded.addSender({ email: 'hello@mail.example.com', name: 'Example' })
        seeded.addSender({ email: 'billing@mail.example.com', name: 'Example billing' })
        seeded.verifyDomain('mail.example.com')
        seeded.addSender({ email: 'news@updates.example.com', name: 'Example news' })
        return seeded
    }, [])
    useStorybookMocks(backend.mocks())
    const { integrations } = useValues(integrationsLogic)
    const { openAddSender } = useActions(addEmailSenderLogic)
    const loaded = integrations !== null
    useEffect(() => {
        if (loaded) {
            openAddSender(domain, 'catalog')
        }
    }, [loaded, domain, openAddSender])
    return <MessageChannels />
}

const meta: Meta<AddSenderArgs> = {
    title: 'Scenes-App/Workflows/Add email sender',
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForLoadersToDisappear: true, snapshotBrowsers: [] },
    },
    render: (args) => <ChannelsWithAddSender {...args} />,
}
export default meta

type Story = StoryObj<AddSenderArgs>

export const PicksAVerifiedDomain: Story = { args: { domain: null } }

export const UnverifiedDomain: Story = { args: { domain: 'updates.example.com' } }

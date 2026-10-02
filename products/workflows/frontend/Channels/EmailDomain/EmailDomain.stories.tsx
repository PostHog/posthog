import { Meta, StoryObj } from '@storybook/react'
import { useEffect, useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { FakeDnsHost, FakeEmailDomainBackend, FakeRecord } from './__mocks__/fakeEmailDomainBackend'
import { emailDomainAgentLogic } from './emailDomainAgentLogic'
import { emailDomainManualSetupLogic } from './emailDomainManualSetupLogic'
import { EmailDomainScene } from './EmailDomainScene'
import { emailDomainStatusLogic } from './emailDomainStatusLogic'

const DOMAIN = 'mail.acme.com'
const EMAIL = `hello@${DOMAIN}`

const halfPublished = (record: FakeRecord, index: number): boolean =>
    ['verification', 'spf'].includes(record.kind) || (record.kind === 'dkim' && index < 3)
const allButOneDkimPublished = (_: FakeRecord, index: number): boolean => index !== 2

type Stage = (backend: FakeEmailDomainBackend, id: string) => void

interface DomainPageArgs {
    host: FakeDnsHost
    seed?: (backend: FakeEmailDomainBackend) => void
    stage?: Stage
}

const seededBackend = (host: FakeDnsHost, seed?: DomainPageArgs['seed']): FakeEmailDomainBackend => {
    const backend = new FakeEmailDomainBackend()
    backend.hostDnsAt('acme.com', host)
    backend.addSender({ email: EMAIL })
    seed?.(backend)
    return backend
}

function Staged({ backend, id, stage }: { backend: FakeEmailDomainBackend; id: string; stage?: Stage }): null {
    useEffect(() => {
        stage?.(backend, id)
    }, [backend, id, stage])
    return null
}

function DomainPage({ host, seed, stage }: DomainPageArgs): JSX.Element {
    const backend = useMemo(() => seededBackend(host, seed), [host, seed])
    const id = String(backend.sender(42)?.id)
    useStorybookMocks(backend.mocks())
    return (
        <>
            <EmailDomainScene id={id} />
            <Staged backend={backend} id={id} stage={stage} />
        </>
    )
}

function UnavailableDomainPage(): JSX.Element {
    const backend = useMemo(() => {
        const seeded = seededBackend('unknown')
        seeded.fail('integration_get', { status: 500, body: { detail: 'Could not reach the email provider' } })
        return seeded
    }, [])
    useStorybookMocks(backend.mocks())
    return <EmailDomainScene id="42" />
}

function NewDomainPage(): JSX.Element {
    const backend = useMemo(() => {
        const empty = new FakeEmailDomainBackend()
        empty.eventHosts = [
            ['https://acme.com', 1_240_000],
            ['https://app.acme.com', 860_000],
        ]
        return empty
    }, [])
    useStorybookMocks(backend.mocks())
    return <EmailDomainScene id="new" />
}

const meta: Meta<DomainPageArgs> = {
    title: 'Scenes-App/Workflows/Email domain setup',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD],
        testOptions: { waitForLoadersToDisappear: true },
    },
    render: (args) => <DomainPage {...args} />,
}
export default meta

type Story = StoryObj<DomainPageArgs>

export const DomainStep: Story = { render: () => <NewDomainPage /> }

export const SettingsNotStarted: Story = {
    args: { host: 'cloudflare', seed: (backend) => backend.withoutSesIdentity(DOMAIN) },
}

export const SettingsCloudflare: Story = { args: { host: 'cloudflare' } }

export const SettingsCloudflareExistingDmarc: Story = {
    args: { host: 'cloudflare', seed: (backend) => backend.preexistingRecords(DOMAIN, ['dmarc']) },
}

export const SettingsCloudflareRecordsRevealed: Story = {
    args: {
        host: 'cloudflare',
        stage: (_, id) => emailDomainManualSetupLogic.findMounted({ id })?.actions.revealRecords(),
    },
}

export const SettingsRoute53: Story = { args: { host: 'route53' } }

export const SettingsUnknownHost: Story = { args: { host: 'unknown' } }

export const Verifying: Story = {
    args: { host: 'route53', seed: (backend) => backend.publishRecords(DOMAIN, halfPublished) },
}

export const VerifyingRecordsFound: Story = {
    args: { host: 'cloudflare', seed: (backend) => backend.publishRecords(DOMAIN) },
}

export const VerifyingPollingStopped: Story = {
    args: {
        host: 'route53',
        seed: (backend) => backend.publishRecords(DOMAIN, halfPublished),
        stage: (_, id) => emailDomainStatusLogic.findMounted({ id })?.actions.stopPolling(),
    },
}

export const VerifyingTemporaryFailure: Story = {
    args: {
        host: 'unknown',
        seed: (backend) => {
            backend.sesConfirms(DOMAIN, ['verification', 'dkim'])
            backend.publishRecords(DOMAIN, ['spf', 'dmarc'])
            backend.sesReports(DOMAIN, 'temporary_failure')
        },
    },
}

export const VerifyingFailed: Story = {
    args: {
        host: 'route53',
        seed: (backend) => {
            backend.publishRecords(DOMAIN, allButOneDkimPublished)
            backend.sesReports(DOMAIN, 'failed')
        },
    },
}

export const Ready: Story = { args: { host: 'cloudflare', seed: (backend) => backend.verifyDomain(DOMAIN) } }

export const Unavailable: Story = { render: () => <UnavailableDomainPage /> }

export const AgentHandoff: Story = {
    args: {
        host: 'route53',
        stage: (_, id) => emailDomainAgentLogic.findMounted({ id })?.actions.openAgentModal(),
    },
    parameters: {
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD, FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_AGENT_SETUP],
    },
}

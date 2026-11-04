import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect, useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { useStorybookMocks } from '~/mocks/browser'

import type { DataSuggestionApi } from '../../generated/api.schemas'
import { FakeDnsHost, FakeEmailDomainBackend, FakeRecord } from './__mocks__/fakeEmailDomainBackend'
import { emailDomainAgentLogic } from './emailDomainAgentLogic'
import { emailDomainManualSetupLogic } from './emailDomainManualSetupLogic'
import { EmailDomainScene } from './EmailDomainScene'
import { emailDomainStatusLogic } from './emailDomainStatusLogic'

const DOMAIN = 'mail.acme.com'
const EMAIL = `hello@${DOMAIN}`
const LONG_DOMAIN = 'updates.hedgebox-mail.com'

const SUGGESTED_WORKFLOWS: DataSuggestionApi[] = [
    {
        id: 'suggestion-welcome',
        name: 'Welcome new teammates',
        description: 'Email a new teammate a getting started guide after they join a workspace.',
        reason: 'teammate_joined fires every day.',
        trigger_event: 'teammate_joined',
        weekly_count: 1_840,
        stage: 'onboarding',
        premade: false,
        step_outline: ['email', 'delay', 'email'],
    },
    {
        id: 'suggestion-trial',
        name: 'Nudge trials before they end',
        description: 'Remind a workspace on a trial three days before it ends, and again on the last day.',
        reason: 'trial_started fires every week.',
        trigger_event: 'trial_started',
        weekly_count: 320,
        stage: 'trial',
        premade: false,
        step_outline: ['delay', 'email', 'delay', 'email'],
    },
    {
        id: 'suggestion-inactive',
        name: 'Win back quiet workspaces',
        description: 'Email the owner of a workspace that has not created a board in 14 days.',
        reason: 'board_created drops off for some workspaces.',
        trigger_event: 'board_created',
        weekly_count: 9_600,
        stage: 'churn_risk',
        premade: false,
        step_outline: ['wait_until', 'branch', 'email'],
    },
]

const halfPublished = (record: FakeRecord, index: number): boolean =>
    ['verification', 'spf'].includes(record.kind) || (record.kind === 'dkim' && index < 3)
const allButOneDkimPublished = (_: FakeRecord, index: number): boolean => index !== 2

type Stage = (backend: FakeEmailDomainBackend, id: string) => void

interface DomainPageArgs {
    host: FakeDnsHost
    email?: string
    seed?: (backend: FakeEmailDomainBackend) => void
    stage?: Stage
    aiApproved?: boolean
}

const seededBackend = (
    host: FakeDnsHost,
    seed?: DomainPageArgs['seed'],
    email: string = EMAIL
): FakeEmailDomainBackend => {
    const backend = new FakeEmailDomainBackend()
    backend.hostDnsAt('acme.com', host)
    backend.addSender({ email })
    seed?.(backend)
    return backend
}

function Staged({ backend, id, stage }: { backend: FakeEmailDomainBackend; id: string; stage?: Stage }): null {
    useEffect(() => {
        stage?.(backend, id)
    }, [backend, id, stage])
    return null
}

function DomainPage({ host, email, seed, stage, aiApproved = false }: DomainPageArgs): JSX.Element {
    const backend = useMemo(() => seededBackend(host, seed, email), [host, seed, email])
    const id = String(backend.sender(42)?.id)
    useStorybookMocks(backend.mocks())
    const { loadCurrentOrganizationSuccess } = useActions(organizationLogic)
    useEffect(() => {
        loadCurrentOrganizationSuccess({ ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: aiApproved })
    }, [aiApproved, loadCurrentOrganizationSuccess])
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

// The checking step keeps its spinner while it polls, so the snapshot cannot wait for loaders to clear.
const pollingStory = { testOptions: { waitForLoadersToDisappear: false } }

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
    parameters: pollingStory,
}

export const VerifyingRecordsFound: Story = {
    args: { host: 'cloudflare', seed: (backend) => backend.publishRecords(DOMAIN) },
    parameters: pollingStory,
}

export const VerifyingPollingStopped: Story = {
    args: {
        host: 'route53',
        seed: (backend) => backend.publishRecords(DOMAIN, halfPublished),
        stage: (_, id) => emailDomainStatusLogic.findMounted({ id })?.actions.stopPolling(),
    },
}

export const VerifyingRecordsInPlace: Story = {
    args: {
        host: 'cloudflare',
        seed: (backend) => backend.publishRecords(DOMAIN),
        stage: (_, id) => emailDomainStatusLogic.findMounted({ id })?.actions.stopPolling(),
    },
    parameters: pollingStory,
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
    parameters: pollingStory,
}

export const VerifyingFailed: Story = {
    args: {
        host: 'route53',
        seed: (backend) => {
            backend.publishRecords(DOMAIN, allButOneDkimPublished)
            backend.sesReports(DOMAIN, 'failed')
        },
    },
    parameters: pollingStory,
}

export const Ready: Story = { args: { host: 'cloudflare', seed: (backend) => backend.verifyDomain(DOMAIN) } }

export const ReadyLongDomain: Story = {
    args: {
        host: 'cloudflare',
        email: `hello@${LONG_DOMAIN}`,
        seed: (backend) => backend.verifyDomain(LONG_DOMAIN),
    },
}

export const ReadyWithSuggestions: Story = {
    args: {
        host: 'cloudflare',
        seed: (backend) => {
            backend.verifyDomain(DOMAIN)
            backend.suggestWorkflows(SUGGESTED_WORKFLOWS)
        },
        aiApproved: true,
    },
}

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

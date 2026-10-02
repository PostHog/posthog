import { MockResolverInfo, Mocks } from '~/mocks/utils'
import { EmailSenderDomainStatus } from '~/types'

import type {
    EmailDomainConnectCheckApi,
    EmailDomainSetupRecordKindEnumApi,
    EmailDomainStatusApi,
    EmailDomainStatusRecordApi,
    IntegrationConfigApi,
    PaginatedIntegrationConfigListApi,
} from 'products/integrations/frontend/generated/api.schemas'

import { HogflowTestResult } from '../../../Workflows/hogflows/steps/types'
import { EmailSenderConfig, EmailSetupMethod } from '../emailDomainSenderLogic'

export type FakeDnsHost = 'cloudflare' | 'route53' | 'unknown'

/** What SES knows about the domain's identity. */
export type FakeSesState = 'none' | 'pending' | 'temporary_failure' | 'failed' | 'verified'

export type FakeEndpoint =
    | 'integration_list'
    | 'integration_get'
    | 'integration_create'
    | 'email_status'
    | 'email_verify'
    | 'email_update'
    | 'domain_connect_check'
    | 'domain_connect_apply_url'
    | 'event_hosts'
    | 'test_email'

export interface FakeFailure {
    status: number
    body?: Record<string, unknown>
}

export interface FakeRequest {
    endpoint: FakeEndpoint
    method: string
    url: string
    body: unknown
}

type RecordKind = EmailDomainSetupRecordKindEnumApi

/** A record the domain needs, before DNS or SES say anything about it. */
export type FakeRecord = Omit<EmailDomainStatusRecordApi, 'status'>

/** Which of a domain's records to touch: a list of kinds, or a predicate over the record and its position. */
export type FakeRecordSelection = RecordKind[] | ((record: FakeRecord, index: number) => boolean)

type RecordTemplate = FakeRecord
type FakeResponse = [status: number, body?: unknown] | object

interface FakeDomain {
    domain: string
    mailFromSubdomain: string
    ses: FakeSesState
    published: Set<string>
    preexisting: Set<RecordKind>
    confirmed: Set<RecordKind>
}

interface Hold {
    promise: Promise<void>
    release: () => void
}

const CHECKED_AT = '2026-01-01T00:00:00Z'
const FIRST_SENDER_ID = 42
const VERIFICATION_TOKEN = 'pSM7OoC2Jl6dNKGRmkc4KZpesve3QP3cUUT2FGZZ1PU='
const DKIM_SELECTORS = [
    'v4fyczifqlyachgcw4jqrsdcbbblc236',
    'fxaevqyhjczvbnhst7funhfphvbo4hv6',
    'xzipw445tsam4wdwe5y33mgkutbsyqaj',
]
const SPF_VALUE = 'v=spf1 include:amazonses.com ~all'

const DNS_HOSTS: Record<FakeDnsHost, EmailDomainConnectCheckApi> = {
    cloudflare: {
        supported: true,
        provider_name: 'Cloudflare',
        available_providers: [],
        dns_host: {
            name: 'Cloudflare',
            dns_settings_url: 'https://dash.cloudflare.com/?to=/:account/:zone/dns/records',
        },
        existing_email_tools: [],
    },
    route53: {
        supported: false,
        provider_name: null,
        available_providers: [],
        dns_host: { name: 'Route 53', dns_settings_url: 'https://console.aws.amazon.com/route53/v2/hostedzones' },
        existing_email_tools: ['Customer.io'],
    },
    unknown: {
        supported: false,
        provider_name: null,
        available_providers: [],
        dns_host: null,
        existing_email_tools: [],
    },
}

const FAKE_USER: IntegrationConfigApi['created_by'] = {
    id: 1,
    uuid: '00000000-0000-0000-0000-000000000001',
    distinct_id: 'fake-user',
    first_name: 'Jane',
    email: 'jane@example.com',
    hedgehog_config: null,
}

const recordKey = (record: Pick<EmailDomainStatusRecordApi, 'type' | 'hostname'>): string =>
    `${record.type} ${record.hostname}`

const recordTemplates = (domain: string, mailFromSubdomain: string): RecordTemplate[] => [
    { kind: 'verification', type: 'TXT', hostname: `_amazonses.${domain}`, value: VERIFICATION_TOKEN, priority: null },
    ...DKIM_SELECTORS.map(
        (selector): RecordTemplate => ({
            kind: 'dkim',
            type: 'CNAME',
            hostname: `${selector}._domainkey.${domain}`,
            value: `${selector}.dkim.amazonses.com`,
            priority: null,
        })
    ),
    { kind: 'spf', type: 'TXT', hostname: domain, value: SPF_VALUE, priority: null },
    {
        kind: 'mail_from_mx',
        type: 'MX',
        hostname: `${mailFromSubdomain}.${domain}`,
        value: 'feedback-smtp.us-east-1.amazonses.com',
        priority: 10,
    },
    {
        kind: 'mail_from_spf',
        type: 'TXT',
        hostname: `${mailFromSubdomain}.${domain}`,
        value: SPF_VALUE,
        priority: null,
    },
    { kind: 'dmarc', type: 'TXT', hostname: `_dmarc.${domain}`, value: 'v=DMARC1; p=none;', priority: null },
]

const domainOfEmail = (email: string): string => email.split('@')[1] ?? ''

const readBody = async (request: Request): Promise<unknown> => {
    try {
        return await request.clone().json()
    } catch {
        return null
    }
}

const createHold = (): Hold => {
    let release = (): void => {}
    const promise = new Promise<void>((resolve) => {
        release = resolve
    })
    return { promise, release }
}

/**
 * The email sending domain backend as the wizard sees it over HTTP: senders, their SES identity and the DNS
 * records published for each domain. A test or story seeds it, registers `mocks()` with MSW and advances the
 * domain with `publishRecords` and `verifyDomain`. Every response is typed with the generated API types.
 */
export class FakeEmailDomainBackend {
    readonly requests: FakeRequest[] = []
    eventHosts: [host: string, count: number][] = []

    private senders = new Map<number, IntegrationConfigApi>()
    private domains = new Map<string, FakeDomain>()
    private dnsHosts = new Map<string, FakeDnsHost>()
    private failures = new Map<FakeEndpoint, FakeFailure>()
    private oneOffFailures = new Map<FakeEndpoint, FakeFailure>()
    private holds = new Map<FakeEndpoint, Hold>()
    private nextSenderId = FIRST_SENDER_ID

    addSender(config: Pick<EmailSenderConfig, 'email'> & Partial<EmailSenderConfig>): IntegrationConfigApi {
        const domain = config.domain ?? domainOfEmail(config.email)
        const sender: IntegrationConfigApi = {
            id: this.nextSenderId++,
            kind: 'email',
            config: {
                provider: 'ses',
                name: 'Acme',
                mail_from_subdomain: 'feedback',
                verified: false,
                ...config,
                domain,
            } satisfies EmailSenderConfig,
            created_at: CHECKED_AT,
            created_by: FAKE_USER,
            errors: '',
            display_name: config.email,
            files_write_requestable: false,
            installation_shared: null,
            installation_status: null,
        }
        this.senders.set(sender.id, sender)
        if (!this.domains.has(domain)) {
            this.domains.set(domain, {
                domain,
                mailFromSubdomain: config.mail_from_subdomain ?? 'feedback',
                ses: 'pending',
                published: new Set(),
                preexisting: new Set(),
                confirmed: new Set(),
            })
        }
        return sender
    }

    sender(id: number): IntegrationConfigApi | undefined {
        return this.senders.get(id)
    }

    senderConfig(id: number): EmailSenderConfig | undefined {
        return this.senders.get(id)?.config as EmailSenderConfig | undefined
    }

    /** Which company answers for the domain's nameservers. Matches subdomains of the given domain too. */
    hostDnsAt(domain: string, host: FakeDnsHost): void {
        this.dnsHosts.set(domain, host)
    }

    /** SES has no identity for the domain yet, so the status has no records to hand out. */
    withoutSesIdentity(domain: string): void {
        this.domainState(domain).ses = 'none'
    }

    /** Records that existed at the DNS host before setup started, such as a DMARC policy. */
    preexistingRecords(domain: string, kinds: RecordKind[]): void {
        kinds.forEach((kind) => this.domainState(domain).preexisting.add(kind))
    }

    /** The person (or Domain Connect) published records at the DNS host. All of them when nothing is selected. */
    publishRecords(domain: string, selection?: FakeRecordSelection): void {
        const state = this.domainState(domain)
        const selected =
            typeof selection === 'function'
                ? selection
                : (record: FakeRecord): boolean => !selection || selection.includes(record.kind)
        recordTemplates(domain, state.mailFromSubdomain)
            .filter(selected)
            .forEach((record) => state.published.add(recordKey(record)))
    }

    /** SES confirmed these parts of the identity, while the domain as a whole is not verified yet. */
    sesConfirms(domain: string, kinds: RecordKind[]): void {
        this.publishRecords(domain, kinds)
        kinds.forEach((kind) => this.domainState(domain).confirmed.add(kind))
    }

    /** SES confirmed the records and marked every sender on the domain as able to send. */
    verifyDomain(domain: string): void {
        this.publishRecords(domain)
        this.domainState(domain).ses = 'verified'
        this.senders.forEach((sender) => {
            const config = sender.config as EmailSenderConfig
            if (config.domain === domain) {
                sender.config = { ...config, verified: true }
            }
        })
    }

    sesReports(domain: string, state: Exclude<FakeSesState, 'verified' | 'none'>): void {
        this.domainState(domain).ses = state
    }

    /** What the DNS host does once the person approves the Domain Connect template. */
    approveDomainConnect(domain: string): void {
        this.publishRecords(domain)
    }

    fail(endpoint: FakeEndpoint, failure: FakeFailure): void {
        this.failures.set(endpoint, failure)
    }

    failOnce(endpoint: FakeEndpoint, failure: FakeFailure): void {
        this.oneOffFailures.set(endpoint, failure)
    }

    recover(endpoint: FakeEndpoint): void {
        this.failures.delete(endpoint)
        this.oneOffFailures.delete(endpoint)
    }

    /** Keeps every response from the endpoint pending until the returned function is called. */
    hold(endpoint: FakeEndpoint): () => void {
        const hold = createHold()
        this.holds.set(endpoint, hold)
        return () => {
            this.holds.delete(endpoint)
            hold.release()
        }
    }

    requestsTo(endpoint: FakeEndpoint): FakeRequest[] {
        return this.requests.filter((request) => request.endpoint === endpoint)
    }

    statusOf(domain: string): EmailDomainStatusApi {
        const state = this.domainState(domain)
        const records =
            state.ses === 'none'
                ? []
                : recordTemplates(domain, state.mailFromSubdomain).map((record) => ({
                      ...record,
                      status: this.recordStatus(state, record),
                  }))
        const allFound = records.length > 0 && records.every((record) => record.status !== 'pending')
        const status = this.overallStatus(state, allFound)
        return {
            status,
            verified: state.ses === 'verified',
            checked_at: CHECKED_AT,
            steps: [
                { key: 'domain_added', state: 'done' },
                { key: 'records_found', state: allFound ? 'done' : 'pending' },
                {
                    key: 'verified',
                    state: state.ses === 'verified' ? 'done' : state.ses === 'failed' ? 'failed' : 'pending',
                },
            ],
            records,
        }
    }

    detectionOf(domain: string): EmailDomainConnectCheckApi {
        const host = [...this.dnsHosts.entries()].find(
            ([registered]) => domain === registered || domain.endsWith(`.${registered}`)
        )?.[1]
        return DNS_HOSTS[host ?? 'unknown']
    }

    mocks(): Mocks {
        return {
            get: {
                '/api/environments/:team_id/integrations/': this.serve('integration_list', () => this.listSenders()),
                '/api/environments/:team_id/integrations/:id/': this.serve('integration_get', ({ params }) =>
                    this.withSender(Number(params.id), (sender) => sender)
                ),
                '/api/environments/:team_id/integrations/:id/email/status/': this.serve('email_status', ({ params }) =>
                    this.withSender(Number(params.id), (sender) =>
                        this.statusOf((sender.config as EmailSenderConfig).domain)
                    )
                ),
                '/api/environments/:team_id/integrations/domain-connect/check/': this.serve(
                    'domain_connect_check',
                    ({ request }) => this.detectionOf(new URL(request.url).searchParams.get('domain') ?? '')
                ),
            },
            post: {
                '/api/environments/:team_id/integrations/': this.serve('integration_create', (_, body) =>
                    this.createSender(body as { config: EmailSenderConfig })
                ),
                '/api/environments/:team_id/integrations/:id/email/verify/': this.serve('email_verify', ({ params }) =>
                    this.withSender(Number(params.id), (sender) => this.restartVerification(sender))
                ),
                '/api/environments/:team_id/integrations/domain-connect/apply-url/': this.serve(
                    'domain_connect_apply_url',
                    (_, body) => this.applyUrl(body as { integration_id: number; redirect_uri: string })
                ),
                '/api/environments/:team_id/query/': this.serve('event_hosts', () => ({ results: this.eventHosts })),
                '/api/environments/:team_id/hog_flows/:id/invocations/': this.serve(
                    'test_email',
                    (): HogflowTestResult => ({ status: 'success', nextActionId: null, logs: [] })
                ),
            },
            patch: {
                '/api/environments/:team_id/integrations/:id/email/': this.serve('email_update', ({ params }, body) =>
                    this.withSender(Number(params.id), (sender) =>
                        this.updateSender(sender, (body as { config: Partial<EmailSenderConfig> }).config)
                    )
                ),
            },
        }
    }

    private serve(
        endpoint: FakeEndpoint,
        respond: (info: MockResolverInfo, body: unknown) => FakeResponse
    ): (info: MockResolverInfo) => Promise<FakeResponse> {
        return async (info) => {
            const body = await readBody(info.request)
            this.requests.push({ endpoint, method: info.request.method, url: info.request.url, body })
            await this.holds.get(endpoint)?.promise
            const failure = this.failureFor(endpoint)
            if (failure) {
                return [failure.status, failure.body ?? { detail: 'The fake backend refused this request' }]
            }
            return respond(info, body)
        }
    }

    private failureFor(endpoint: FakeEndpoint): FakeFailure | undefined {
        const oneOff = this.oneOffFailures.get(endpoint)
        if (oneOff) {
            this.oneOffFailures.delete(endpoint)
            return oneOff
        }
        return this.failures.get(endpoint)
    }

    private domainState(domain: string): FakeDomain {
        const state = this.domains.get(domain)
        if (!state) {
            throw new Error(`The fake backend has no sender for ${domain}. Add one with addSender first.`)
        }
        return state
    }

    private withSender(id: number, respond: (sender: IntegrationConfigApi) => FakeResponse): FakeResponse {
        const sender = this.senders.get(id)
        return sender ? respond(sender) : [404, { detail: 'Not found.' }]
    }

    private recordStatus(state: FakeDomain, record: RecordTemplate): EmailDomainStatusRecordApi['status'] {
        if (state.ses === 'verified' || state.confirmed.has(record.kind)) {
            return 'verified'
        }
        const published = state.published.has(recordKey(record)) || state.preexisting.has(record.kind)
        if (!published) {
            return 'pending'
        }
        return record.kind === 'dmarc' ? 'verified' : 'found'
    }

    private overallStatus(state: FakeDomain, allFound: boolean): EmailDomainStatusApi['status'] {
        switch (state.ses) {
            case 'none':
                return 'not_started'
            case 'verified':
                return 'verified'
            case 'failed':
                return 'failed'
            case 'temporary_failure':
                return 'temporary_failure'
            case 'pending':
                return allFound ? 'records_found' : 'pending'
        }
    }

    private listSenders(): PaginatedIntegrationConfigListApi {
        const results = [...this.senders.values()]
        return { count: results.length, next: null, previous: null, results }
    }

    private createSender(body: { config: EmailSenderConfig }): IntegrationConfigApi {
        return this.addSender(body.config)
    }

    private updateSender(sender: IntegrationConfigApi, config: Partial<EmailSenderConfig>): IntegrationConfigApi {
        const current = sender.config as EmailSenderConfig
        sender.config = {
            ...current,
            name: config.name ?? current.name,
            mail_from_subdomain: config.mail_from_subdomain ?? current.mail_from_subdomain,
            setup_method: config.setup_method ?? current.setup_method,
        } satisfies EmailSenderConfig
        return sender
    }

    private restartVerification(sender: IntegrationConfigApi): EmailSenderDomainStatus {
        const state = this.domainState((sender.config as EmailSenderConfig).domain)
        if (state.ses !== 'verified') {
            state.ses = 'pending'
        }
        return { status: 'pending', dnsRecords: [] }
    }

    private applyUrl(body: { integration_id: number; redirect_uri: string }): FakeResponse {
        const sender = this.senders.get(body.integration_id)
        if (!sender) {
            return [404, { detail: 'Not found.' }]
        }
        const method: EmailSetupMethod = 'auto'
        this.updateSender(sender, { setup_method: method })
        const domain = (sender.config as EmailSenderConfig).domain
        const url = new URL('https://dns.example.com/domain-connect/apply')
        url.searchParams.set('domain', domain)
        url.searchParams.set('redirect_uri', body.redirect_uri)
        return { url: url.toString() }
    }
}

import type { AuthProject, StoredAccount } from '@/auth/authStore'

function project(id: number, name: string, organizationId: string, organizationName: string): AuthProject {
    return { id, name, organizationId, organizationName }
}

function account(overrides: Partial<StoredAccount> & Pick<StoredAccount, 'key' | 'host' | 'region'>): StoredAccount {
    return {
        clientId: 'client-id',
        method: 'oauth',
        userUuid: `${overrides.key}-user`,
        user: null,
        organizations: [],
        projects: [],
        projectId: null,
        needsSignIn: false,
        lastUsedAt: 0,
        ...overrides,
    }
}

/** Test accounts: one person on US and EU Cloud, and on a self-hosted instance whose session ended. */
export const US_ACCOUNT = account({
    key: 'us-account',
    host: 'https://us.posthog.com',
    region: 'us',
    user: { uuid: 'us-user', distinctId: 'us-user', email: 'maya@example.com', name: 'Maya Okafor' },
    projects: [
        project(1, 'Hedgebox web', 'org-hedgebox', 'Hedgebox'),
        project(2, 'Hedgebox iOS', 'org-hedgebox', 'Hedgebox'),
        project(3, 'Northwind web', 'org-northwind', 'Northwind Studio'),
    ],
    projectId: 1,
    lastUsedAt: 3,
})

export const EU_ACCOUNT = account({
    key: 'eu-account',
    host: 'https://eu.posthog.com',
    region: 'eu',
    user: { uuid: 'eu-user', distinctId: 'eu-user', email: 'maya@example.com', name: 'Maya Okafor' },
    projects: [project(1, 'Bluebell web', 'org-bluebell', 'Bluebell Labs')],
    projectId: 1,
    lastUsedAt: 2,
})

export const SELF_HOSTED_ACCOUNT = account({
    key: 'self-hosted-account',
    host: 'https://posthog.example.org',
    region: 'custom',
    user: { uuid: 'sh-user', distinctId: 'sh-user', email: 'maya@example.org', name: 'Maya Okafor' },
    projects: [project(7, 'Internal tools', 'org-example', 'Example Labs')],
    projectId: 7,
    needsSignIn: true,
    lastUsedAt: 1,
})

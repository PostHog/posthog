import AsyncStorage from '@react-native-async-storage/async-storage'
import { AppState, type NativeEventSubscription } from 'react-native'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { ApiError, endSessionRequests, NotSignedInError, setAuthProvider } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { TransportError } from '@/api/transport'
import { identify, resetAnalytics, track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { createPersistHydrationGate } from '@/lib/persistHydration'

import {
    type Account,
    type AuthOrganization,
    type AuthProject,
    type AuthUser,
    loadAccount,
    loadAccountWithCredentials,
    pickProjectId,
} from './account'
import { type AccountRef, accountKey } from './accountKey'
import { type AuthorizeResult, authorize, OAuthError, refreshTokens, revokeToken } from './oauth'
import { type RegionId, regionForHost, validateHost } from './regions'
import {
    AccountAlreadyAddedError,
    AccountLoadError,
    AccountNeedsSignInError,
    AccountUnavailableError,
    accountLoadKind,
    SignInInputError,
} from './signInErrors'
import {
    activateAccountSession,
    clearSession,
    forgetAccountSlot,
    getSessionAccountKey,
    getSessionIdentity,
    getSessionTokens,
    type LoadedAccounts,
    loadAccounts,
    readAccountSession,
    type SessionIdentity,
    type SessionTokens,
    type StoredSession,
    saveRefreshedTokens,
    sessionGeneration,
    setSessionTokens,
    writeAccountSlot,
} from './tokens'

export type { AuthOrganization, AuthProject, AuthUser } from './account'
export type { AccountRef } from './accountKey'
export { AccountAlreadyAddedError, AccountNeedsSignInError, AccountUnavailableError } from './signInErrors'

export type AuthStatus = 'loading' | 'signed_out' | 'signed_in'
export type AuthMethod = 'oauth' | 'personal_api_key'
export type ProjectSwitchSource = 'nav_menu' | 'settings' | 'push' | 'link'
/** `sign_out` is the switch to another account after the active one signs out. */
export type AccountSwitchSource = ProjectSwitchSource | 'sign_in' | 'sign_out'

export interface StoredAccount {
    key: string
    host: string
    clientId: string | null
    method: AuthMethod
    region: RegionId
    userUuid: string
    /** Null until the account loads once, such as for a login that the keychain kept across a reinstall. */
    user: AuthUser | null
    organizations: AuthOrganization[]
    projects: AuthProject[]
    /** The project last picked in this account. */
    projectId: number | null
    /** Its credentials stopped working or are gone. Only a new sign-in brings it back. */
    needsSignIn: boolean
    /** Epoch ms of the last time it became the active account. */
    lastUsedAt: number
}

export interface AuthState {
    status: AuthStatus
    signedIn: boolean
    /** The region of the last sign-in. Kept after sign out so the sign-in screen starts there. */
    region: RegionId
    // The fields from `host` to `projectName` mirror the active account, so screens read one session.
    host: string | null
    clientId: string | null
    method: AuthMethod | null
    user: AuthUser | null
    organizations: AuthOrganization[]
    projects: AuthProject[]
    projectId: number | null
    projectName: string | null
    accountLoading: boolean
    accountError: string | null
    signedOutReason: 'expired' | null
    /** The account whose active session expired, until a sign-in, a switch or a sign out of it. */
    expiredAccountKey: string | null
    accounts: StoredAccount[]
    activeAccountKey: string | null
    /**
     * Accounts whose slot the last read could not read, such as before the first unlock. They are not usable and not
     * signed out: a switch to one reads its slot again, and a sign-in to one replaces its slot.
     */
    unreadableAccountKeys: string[]
    /** Accounts whose slot a sign out or expiry failed to delete. The next launch deletes them before it reads any. */
    pendingSlotRemovals: string[]
    /**
     * The user signed out on purpose, so the next sign-in must not reuse the browser's web session, which still
     * belongs to that account. An expiry does not set it. A successful sign-in clears it.
     */
    freshLoginNext: boolean
    restore: () => Promise<void>
    /**
     * Signs in with the browser. With a session active it adds the account and switches to it, and the earlier account
     * stays signed in. `freshLogin` asks for a browser session without the web app's cookies. `reauth` names the account
     * the caller signs in again: when the browser returns it, its slot is replaced and it stays or becomes active.
     */
    signIn: (host: string, clientId: string, options?: { freshLogin?: boolean; reauth?: string }) => Promise<void>
    /** Development builds only. The personal API key never refreshes. */
    signInWithPersonalApiKey: (host: string, key: string) => Promise<void>
    selectProject: (projectId: number, from: ProjectSwitchSource) => void
    reloadAccount: () => Promise<void>
    /** Changes the active account's organizations in the session fields and in its account entry. */
    updateOrganizations: (update: (organizations: AuthOrganization[]) => AuthOrganization[]) => void
    /** `projectId` applies when that account has the project. */
    switchAccount: (key: string, options: { projectId?: number; from: AccountSwitchSource }) => Promise<void>
    /** Signs out of the active account, then switches to the account used most recently, if one can sign in. */
    signOut: () => Promise<void>
    /** For an inactive account the session stays as it is. */
    signOutAccount: (key: string) => Promise<void>
    signOutAll: () => Promise<void>
}

const RESTORE_REFRESH_MARGIN_MS = 60_000

/** Refresh at launch or on foreground when the access token has less than this left, so the home screen widget's copy stays valid. */
const FOREGROUND_REFRESH_MARGIN_MS = 24 * 60 * 60_000

type SignOutTask = () => Promise<undefined | (() => void)>
type SessionEndTask = () => void | Promise<void>
type AccountRemovedTask = (account: AccountRef) => void | Promise<void>
type AccountSwitchTask = (next: AccountRef) => void | Promise<void>
type InactiveSignOutTask = (account: AccountRef) => Promise<void>
type SwitchRollbackTask = (account: AccountRef) => void | Promise<void>

const signOutTasks = new Set<SignOutTask>()
const sessionEndTasks = new Set<SessionEndTask>()
const accountRemovedTasks = new Set<AccountRemovedTask>()
const accountSwitchTasks = new Set<AccountSwitchTask>()
const inactiveSignOutTasks = new Set<InactiveSignOutTask>()
const switchRollbackTasks = new Set<SwitchRollbackTask>()

function register<T>(tasks: Set<T>, task: T): () => void {
    tasks.add(task)
    return () => {
        tasks.delete(task)
    }
}

/**
 * Registers work that must run while the active account's session is still valid, before signing out of that account
 * drops its token. A thrown error stops the sign out, and the returned function undoes the task's own changes.
 */
export function addSignOutTask(task: SignOutTask): () => void {
    return register(signOutTasks, task)
}

/**
 * Registers in-memory cleanup for every time the active session leaves memory: an account switch, a sign out and an
 * expired session. It runs after the screens unmount and may run after the token is gone, so it must not call the API.
 * It must not delete persisted data either, because a switch keeps the account and its data on the device. Use
 * `addAccountRemovedTask` for that.
 */
export function addSessionEndTask(task: SessionEndTask): () => void {
    return register(sessionEndTasks, task)
}

/**
 * Registers the purge of persisted data that belongs to exactly `account`, when that account leaves the device: a sign
 * out of it, active or not, and an expiry of its credentials. It may run while another account is active, so it must
 * touch only `account`'s data and must not call the API.
 */
export function addAccountRemovedTask(task: AccountRemovedTask): () => void {
    return register(accountRemovedTasks, task)
}

/**
 * Registers work for the start of an account switch, while the token of the account that is left is still valid and
 * its screens are still mounted. `next` is the account the switch goes to. The switch awaits the task and ignores its
 * failure, so the task must bound its own time.
 */
export function addAccountSwitchTask(task: AccountSwitchTask): () => void {
    return register(accountSwitchTasks, task)
}

/**
 * Registers work that runs before an account that is not the session signs out, while its slot still holds its tokens.
 * The task reads that account's credentials itself, from its own slot. The sign out awaits the task and ignores its
 * failure, so the task must bound its own time.
 */
export function addInactiveSignOutTask(task: InactiveSignOutTask): () => void {
    return register(inactiveSignOutTasks, task)
}

/**
 * Registers work for a switch that failed after its switch tasks ran, when the session goes back to `account`. A task
 * undoes what its switch task did for that account.
 */
export function addSwitchRollbackTask(task: SwitchRollbackTask): () => void {
    return register(switchRollbackTasks, task)
}

async function runTasks<A extends unknown[]>(tasks: Set<(...args: A) => unknown>, ...args: A): Promise<void> {
    await Promise.allSettled([...tasks].map(async (task) => task(...args)))
}

const SIGNED_OUT_ACCOUNT = {
    status: 'signed_out',
    signedIn: false,
    method: null,
    user: null,
    organizations: [],
    projects: [],
    projectId: null,
    projectName: null,
    accountLoading: false,
    accountError: null,
} satisfies Partial<AuthState>

function projectNameFor(projects: AuthProject[], projectId: number | null): string | null {
    return projects.find((project) => project.id === projectId)?.name ?? null
}

function mirrorOf(account: StoredAccount): Partial<AuthState> {
    return {
        host: account.host,
        clientId: account.clientId,
        method: account.method,
        region: account.region,
        user: account.user,
        organizations: account.organizations,
        projects: account.projects,
        projectId: account.projectId,
        projectName: projectNameFor(account.projects, account.projectId),
    }
}

function refOf(account: StoredAccount): AccountRef {
    return { key: account.key, host: account.host, userUuid: account.userUuid }
}

function withAccount(accounts: StoredAccount[], account: StoredAccount): StoredAccount[] {
    return accounts.some((existing) => existing.key === account.key)
        ? accounts.map((existing) => (existing.key === account.key ? account : existing))
        : [...accounts, account]
}

function isUsable(account: StoredAccount, unreadable: readonly string[]): boolean {
    return !account.needsSignIn && !unreadable.includes(account.key)
}

/** Keeps only what names the account. Its organizations and projects load again after its next sign-in. */
function expiredAccount(account: StoredAccount): StoredAccount {
    const { user } = account
    return {
        ...account,
        user: user ? { uuid: user.uuid, distinctId: user.distinctId, email: user.email, name: user.name } : null,
        organizations: [],
        projects: [],
        projectId: null,
        needsSignIn: true,
    }
}

function markNeedsSignIn(accounts: StoredAccount[], key: string): StoredAccount[] {
    return accounts.map((account) => (account.key === key ? expiredAccount(account) : account))
}

function without(keys: readonly string[], key: string): string[] {
    return keys.filter((candidate) => candidate !== key)
}

/** The accounts the persisted metadata and the token slots describe together, after a launch reads the slots. */
function reconcileAccounts(state: AuthState, loaded: LoadedAccounts, now: number): StoredAccount[] {
    const { keys } = loaded
    if (keys === null) {
        return state.accounts
    }
    const stored = loaded.stored.filter(({ key }) => !state.pendingSlotRemovals.includes(key))
    const known = new Set(state.accounts.map((account) => account.key))
    const accounts = state.accounts.map((account) => (keys.includes(account.key) ? account : expiredAccount(account)))
    for (const { key, identity } of stored) {
        if (known.has(key)) {
            continue
        }
        // Before multi-account, the session fields were the one account's metadata. They describe this slot only
        // when they name its owner.
        const legacy =
            state.host === identity.host &&
            state.clientId === identity.clientId &&
            state.method === identity.method &&
            state.user?.uuid === identity.userUuid
        accounts.push({
            key,
            host: identity.host,
            clientId: identity.clientId,
            method: identity.method,
            region: regionForHost(identity.host),
            userUuid: identity.userUuid,
            user: legacy ? state.user : null,
            organizations: legacy ? state.organizations : [],
            projects: legacy ? state.projects : [],
            projectId: legacy ? state.projectId : null,
            needsSignIn: false,
            lastUsedAt: key === loaded.active?.key ? now : 0,
        })
    }
    return accounts.map((account) =>
        stored.some(({ key }) => key === account.key) ? { ...account, needsSignIn: false } : account
    )
}

function accountLoadMessage(error: unknown, method: AuthMethod): string {
    if (error instanceof NotSignedInError) {
        return method === 'personal_api_key'
            ? "PostHog didn't accept that key. Check that it is a personal API key with the user:read, organization:read and project:read scopes."
            : "PostHog didn't accept the new session. Try signing in again."
    }
    if (error instanceof ApiError && error.status === 403) {
        return `PostHog didn't share your account details with the app. ${error.detail ?? 'Check the key or app scopes and try again.'}`
    }
    if (error instanceof ApiError) {
        return `Couldn't load your account. ${error.message}`
    }
    if (error instanceof TransportError) {
        return error.message
    }
    return toError(error).message
}

function sameCredentials(a: SessionTokens, b: SessionTokens): boolean {
    return a.kind === 'oauth' ? a.refreshToken === b.refreshToken : a.accessToken === b.accessToken
}

function revokeStored({ tokens, identity }: Pick<StoredSession, 'tokens' | 'identity'>): void {
    if (tokens.kind === 'oauth' && tokens.refreshToken && identity.clientId) {
        void revokeToken({ host: identity.host, clientId: identity.clientId, token: tokens.refreshToken })
    }
}

/** In-flight work that callers of one session share. A caller from another session starts its own. */
interface SessionTask<T> {
    session: number
    promise: Promise<T>
}

let restoring: Promise<void> | null = null
/** The last restore could not read storage and found no session, so a later one may still find it. */
let restoreIncomplete = false
let reloading: SessionTask<void> | null = null
let refreshing: SessionTask<string | null> | null = null
// Reads of an account's slot for a switch, a sign out or a new sign-in wait for its refresh, so they see the rotated pair.
const accountRefreshes = new Map<string, Promise<unknown>>()
let signInIntent = 0
let sessionTransitions: Promise<void> = Promise.resolve()
let transitionsRunning = 0
const hydration = createPersistHydrationGate()
let settleLaunch: (account: AccountRef | null) => void = () => undefined
const launched = new Promise<AccountRef | null>((resolve) => {
    settleLaunch = resolve
})

function serializeSessionTransition<T>(work: () => Promise<T>): Promise<T> {
    const run = async (): Promise<T> => {
        transitionsRunning += 1
        try {
            return await work()
        } finally {
            transitionsRunning -= 1
        }
    }
    const result = sessionTransitions.then(run, run)
    sessionTransitions = result.then(
        () => undefined,
        () => undefined
    )
    return result
}

async function settleAccountRefresh(key: string | null): Promise<void> {
    if (key) {
        await accountRefreshes.get(key)?.catch(() => undefined)
    }
}

async function runSignOutTasks(): Promise<(() => void)[]> {
    const recoveries: (() => void)[] = []
    try {
        for (const task of signOutTasks) {
            const recover = await task()
            if (recover) {
                recoveries.push(recover)
            }
        }
        return recoveries
    } catch (error) {
        for (const recover of recoveries) {
            recover()
        }
        throw error
    }
}

/**
 * Resolves after the first restore that read storage, with the account it made active. Stores that kept data before
 * multi-account use it to give that data to its owner, so a launch that could not read storage leaves it pending.
 */
export function launchAccount(): Promise<AccountRef | null> {
    return launched
}

type PersistedAuth = Pick<
    AuthState,
    | 'region'
    | 'host'
    | 'clientId'
    | 'method'
    | 'user'
    | 'organizations'
    | 'projects'
    | 'projectId'
    | 'projectName'
    | 'signedOutReason'
    | 'expiredAccountKey'
    | 'accounts'
    | 'activeAccountKey'
    | 'freshLoginNext'
    | 'pendingSlotRemovals'
>

export const useAuthStore = create<AuthState>()(
    persist<AuthState, [], [], Partial<PersistedAuth>>(
        (set, get) => {
            /** Sets session fields and copies them into the active account's entry, so both stay one record. */
            const setActive = (patch: Partial<AuthState>): void => {
                set((state) => {
                    const next = { ...state, ...patch }
                    return {
                        ...patch,
                        accounts: state.accounts.map((account) =>
                            account.key === state.activeAccountKey
                                ? {
                                      ...account,
                                      user: next.user,
                                      organizations: next.organizations,
                                      projects: next.projects,
                                      projectId: next.projectId,
                                  }
                                : account
                        ),
                    }
                })
            }

            const accountFields = (account: Account, preferProjectId: number | null): Partial<AuthState> => {
                const projectId = pickProjectId(account.projects, [preferProjectId, account.webTeamId])
                return {
                    user: account.user,
                    organizations: account.organizations,
                    projects: account.projects,
                    projectId,
                    projectName: projectNameFor(account.projects, projectId),
                    accountError: null,
                }
            }

            const changeProject = (projectId: number, from: AccountSwitchSource): void => {
                const { projects, projectId: current } = get()
                const project = projects.find((candidate) => candidate.id === projectId)
                if (!project || projectId === current) {
                    return
                }
                setActive({ projectId, projectName: project.name })
                track('mobile_project_switched', { from })
                // Every cached query belongs to the previous project. Reset drops the data, so no
                // screen shows the old project's reports, and refetches what is on screen.
                void queryClient.resetQueries()
            }

            const forgetSlot = async (key: string): Promise<void> => {
                if (!(await forgetAccountSlot(key))) {
                    set((state) => ({ pendingSlotRemovals: [...without(state.pendingSlotRemovals, key), key] }))
                }
            }

            /** Gives the session back to the account that a failed switch started to leave. */
            const resume = (leavingUser: AuthUser | null, sameAccount: boolean): void => {
                setSessionTokens(getSessionTokens(), getSessionIdentity(), getSessionAccountKey())
                set({ status: 'signed_in', signedIn: true })
                if (sameAccount) {
                    return
                }
                if (leavingUser) {
                    identify(leavingUser.distinctId)
                }
                const account = get().accounts.find((candidate) => candidate.key === get().activeAccountKey)
                if (account) {
                    void runTasks(switchRollbackTasks, refOf(account))
                }
            }

            /**
             * Replaces the in-memory session with `session`. A session that is active first runs the switch tasks,
             * ends its requests, unmounts its screens and runs the session-end tasks. `sameAccount` signs the active
             * account in again, so it skips what a change of account needs. Returns false when `canPublish` turned
             * false, and gives the session back to the earlier account when the switch fails.
             */
            const enterAccount = async ({
                session,
                account,
                canPublish,
                beforeLeave,
                sameAccount = false,
            }: {
                session: StoredSession
                account: StoredAccount
                canPublish: () => boolean
                beforeLeave?: () => void
                sameAccount?: boolean
            }): Promise<boolean> => {
                if (!canPublish()) {
                    return false
                }
                const leaving = get().status === 'signed_in' && getSessionTokens() !== null
                const leavingUser = get().user
                if (leaving) {
                    beforeLeave?.()
                    if (!sameAccount) {
                        await runTasks(accountSwitchTasks, refOf(account))
                    }
                    // The continuations of the leaving session's requests run here, under its caches and analytics.
                    await endSessionRequests()
                    reloading = null
                    // The root layout unmounts every screen while the status is loading.
                    set({ status: 'loading', signedIn: false })
                    await runTasks(sessionEndTasks)
                    // Before activation, because its token listeners can capture events.
                    if (!sameAccount) {
                        resetAnalytics()
                    }
                }
                let committed = false
                try {
                    committed = await activateAccountSession(session, canPublish, () => {
                        // Query keys carry the host and project but not the user, so no cached read may outlive the switch.
                        queryClient.clear()
                        set((state) => ({
                            ...mirrorOf(account),
                            accounts: withAccount(state.accounts, account),
                            activeAccountKey: account.key,
                            unreadableAccountKeys: without(state.unreadableAccountKeys, account.key),
                            status: account.user ? 'signed_in' : 'loading',
                            signedIn: account.user !== null,
                            signedOutReason: null,
                            expiredAccountKey: null,
                            accountLoading: false,
                            accountError: null,
                        }))
                    })
                } finally {
                    if (leaving && !committed) {
                        resume(leavingUser, sameAccount)
                    }
                }
                if (!committed) {
                    return false
                }
                if (!account.user) {
                    await get().reloadAccount()
                    set({ status: 'signed_in', signedIn: true })
                }
                const user = get().user
                if (user) {
                    identify(user.distinctId)
                }
                return true
            }

            const expireStoredAccount = async (key: string): Promise<void> => {
                const account = get().accounts.find((candidate) => candidate.key === key)
                await forgetSlot(key)
                set((state) => ({ accounts: markNeedsSignIn(state.accounts, key) }))
                if (account) {
                    await runTasks(accountRemovedTasks, refOf(account))
                }
            }

            /**
             * Reads an inactive account's slot for a switch. A token that ends within the restore margin is refreshed
             * with that account's own host, client and refresh token, and the new pair goes back to its own slot.
             */
            const preflight = async (target: StoredAccount): Promise<StoredSession> => {
                await settleAccountRefresh(target.key)
                const read = await readAccountSession(target.key)
                if (read.kind === 'unreadable') {
                    set((state) => ({
                        unreadableAccountKeys: [...without(state.unreadableAccountKeys, target.key), target.key],
                    }))
                    throw new AccountUnavailableError(target)
                }
                set((state) => ({ unreadableAccountKeys: without(state.unreadableAccountKeys, target.key) }))
                if (read.kind === 'missing') {
                    await expireStoredAccount(target.key)
                    throw new AccountNeedsSignInError(target)
                }
                const stored = read.session
                const { tokens, identity } = stored
                if (
                    tokens.kind !== 'oauth' ||
                    tokens.expiresAt === null ||
                    tokens.expiresAt - Date.now() >= RESTORE_REFRESH_MARGIN_MS ||
                    !tokens.refreshToken ||
                    !identity.clientId
                ) {
                    return stored
                }
                let next: SessionTokens
                try {
                    next = await refreshTokens({
                        host: identity.host,
                        clientId: identity.clientId,
                        refreshToken: tokens.refreshToken,
                        grantedScopes: tokens.grantedScopes,
                        requestedScopes: tokens.requestedScopes,
                    })
                } catch (error) {
                    if (error instanceof OAuthError && error.kind === 'session_expired') {
                        await expireStoredAccount(target.key)
                        throw new AccountNeedsSignInError(target)
                    }
                    // Offline or a server error: the stored token may still work, as at launch.
                    return stored
                }
                const saved = await saveRefreshedTokens({
                    key: target.key,
                    owner: identity,
                    used: tokens.refreshToken,
                    tokens: next,
                })
                if (saved === 'gone') {
                    revokeStored({ tokens: next, identity })
                    await expireStoredAccount(target.key)
                    throw new AccountNeedsSignInError(target)
                }
                return { ...stored, tokens: next }
            }

            const switchTo = async (
                target: StoredAccount,
                {
                    projectId,
                    from,
                    canPublish,
                }: { projectId?: number; from: AccountSwitchSource; canPublish: () => boolean }
            ): Promise<boolean> => {
                if (target.needsSignIn) {
                    throw new AccountNeedsSignInError(target)
                }
                const session = await preflight(target)
                const chosen =
                    projectId !== undefined && target.projects.some((project) => project.id === projectId)
                        ? projectId
                        : target.projectId
                const accountCount = get().accounts.length
                let tracked = false
                const entered = await enterAccount({
                    session,
                    account: { ...target, projectId: chosen, lastUsedAt: Date.now() },
                    canPublish,
                    // Before the reset, so the event belongs to the user who switched.
                    beforeLeave: () => {
                        tracked = true
                        track('mobile_account_switched', { from, account_count: accountCount })
                    },
                })
                if (!entered) {
                    return false
                }
                if (!tracked) {
                    track('mobile_account_switched', { from, account_count: accountCount })
                }
                void get().reloadAccount()
                refreshBeforeForegroundMargin()
                return true
            }

            /** Switches to the most recently used account that can still sign in. False when none can. */
            const activateNext = async (canPublish: () => boolean): Promise<boolean> => {
                const candidates = get()
                    .accounts.filter((account) => !account.needsSignIn)
                    .sort((a, b) => b.lastUsedAt - a.lastUsedAt)
                for (const candidate of candidates) {
                    try {
                        if (await switchTo(candidate, { from: 'sign_out', canPublish })) {
                            return true
                        }
                        break
                    } catch (error) {
                        if (!(error instanceof AccountNeedsSignInError || error instanceof AccountUnavailableError)) {
                            break
                        }
                    }
                }
                set({ status: 'signed_out', signedIn: false })
                return false
            }

            /** Runs inside a transition. */
            const signOutActive = async (thenSwitch: boolean): Promise<void> => {
                const { status } = get()
                if (status === 'signed_out') {
                    return
                }
                if (status === 'signed_in') {
                    await runSignOutTasks()
                }
                // A refresh in flight rotates the token, so the revocation must wait for the pair it stores.
                await settleAccountRefresh(getSessionAccountKey())
                const tokens = getSessionTokens()
                const owner = getSessionIdentity()
                if (tokens?.kind === 'oauth' && tokens.refreshToken && owner?.clientId) {
                    await revokeToken({ host: owner.host, clientId: owner.clientId, token: tokens.refreshToken })
                }
                const next =
                    thenSwitch &&
                    get().accounts.some((account) => !account.needsSignIn && account.key !== get().activeAccountKey)
                await endActiveSession('user', next ? 'loading' : 'signed_out')
                set({ freshLoginNext: true })
                if (next) {
                    const intent = signInIntent
                    await activateNext(() => intent === signInIntent)
                }
            }

            const signOutInactive = async (account: StoredAccount): Promise<void> => {
                await runTasks(inactiveSignOutTasks, refOf(account))
                await settleAccountRefresh(account.key)
                const read = await readAccountSession(account.key)
                if (read.kind === 'ok') {
                    const { tokens, identity } = read.session
                    if (tokens.kind === 'oauth' && tokens.refreshToken && identity.clientId) {
                        await revokeToken({
                            host: identity.host,
                            clientId: identity.clientId,
                            token: tokens.refreshToken,
                        })
                    }
                }
                await forgetSlot(account.key)
                set((state) => ({
                    accounts: state.accounts.filter((candidate) => candidate.key !== account.key),
                    unreadableAccountKeys: without(state.unreadableAccountKeys, account.key),
                    freshLoginNext: true,
                    ...(state.expiredAccountKey === account.key
                        ? { expiredAccountKey: null, signedOutReason: null }
                        : {}),
                }))
                track('mobile_account_removed', { account_count: get().accounts.length, region: account.region })
                await runTasks(accountRemovedTasks, refOf(account))
            }

            /**
             * `kept` turns true when a failure left the new tokens in the account's slot, because what the slot held
             * could not be read back. The caller must not revoke them then.
             */
            const completeSignIn = async (
                tokens: SessionTokens,
                method: AuthMethod,
                host: string,
                clientId: string | null,
                intent: number,
                reauth: string | undefined,
                browser: Omit<AuthorizeResult, 'tokens'>,
                ownership: { kept: boolean }
            ): Promise<void> => {
                let account: Account
                try {
                    account = await loadAccountWithCredentials(host, tokens.accessToken)
                } catch (error) {
                    throw new AccountLoadError(accountLoadKind(error), accountLoadMessage(error, method))
                }
                const key = await accountKey(host, account.user.uuid)
                await serializeSessionTransition(async () => {
                    if (intent !== signInIntent) {
                        throw new OAuthError('cancelled')
                    }
                    const state = get()
                    const existing = state.accounts.find((candidate) => candidate.key === key)
                    const sessionActive = state.status === 'signed_in'
                    // While signed out, a sign-in to a stored account is how the user gets back in, so it never fails.
                    if (
                        existing &&
                        reauth !== key &&
                        sessionActive &&
                        isUsable(existing, state.unreadableAccountKeys)
                    ) {
                        throw new AccountAlreadyAddedError(key, account.user.email, host, browser)
                    }
                    await settleAccountRefresh(key)
                    const identity: SessionIdentity = { host, clientId, method, userUuid: account.user.uuid }
                    const region = regionForHost(host)
                    const slot = await writeAccountSlot(key, tokens, identity)
                    const projectId = pickProjectId(account.projects, [existing?.projectId, account.webTeamId])
                    let entered = false
                    try {
                        entered = await enterAccount({
                            session: { key, identity, tokens },
                            account: {
                                key,
                                host,
                                clientId,
                                method,
                                region,
                                userUuid: account.user.uuid,
                                user: account.user,
                                organizations: account.organizations,
                                projects: account.projects,
                                projectId,
                                needsSignIn: false,
                                lastUsedAt: Date.now(),
                            },
                            canPublish: () => intent === signInIntent,
                            sameAccount: sessionActive && state.activeAccountKey === key,
                        })
                    } finally {
                        if (!entered && (await slot.undo()) === 'kept') {
                            ownership.kept = true
                        }
                    }
                    if (!entered) {
                        throw new OAuthError('cancelled')
                    }
                    set((current) => ({
                        freshLoginNext: false,
                        pendingSlotRemovals: without(current.pendingSlotRemovals, key),
                    }))
                    track('mobile_signed_in', { method, region })
                    if (!existing) {
                        track('mobile_account_added', {
                            account_count: get().accounts.length,
                            region,
                            select_account: browser.selectAccount,
                        })
                    }
                    if (slot.replaced && !sameCredentials(slot.replaced.tokens, tokens)) {
                        revokeStored(slot.replaced)
                    }
                })
            }

            return {
                status: 'loading',
                signedIn: false,
                region: 'us',
                host: null,
                clientId: null,
                method: null,
                user: null,
                organizations: [],
                projects: [],
                projectId: null,
                projectName: null,
                accountLoading: false,
                accountError: null,
                signedOutReason: null,
                expiredAccountKey: null,
                accounts: [],
                activeAccountKey: null,
                unreadableAccountKeys: [],
                pendingSlotRemovals: [],
                freshLoginNext: false,

                restore: () => {
                    restoring ??= (async () => {
                        let active: StoredAccount | undefined
                        try {
                            await waitForHydration()
                            await finishSlotRemovals()
                            const loaded = await loadAccounts()
                            const now = Date.now()
                            const state = get()
                            const accounts = reconcileAccounts(state, loaded, now)
                            const unreadableAccountKeys =
                                loaded.keys === null ? accounts.map((account) => account.key) : loaded.unreadable
                            const owner = getSessionIdentity()
                            active = state.pendingSlotRemovals.includes(loaded.active?.key ?? '')
                                ? undefined
                                : accounts.find((account) => account.key === loaded.active?.key)
                            restoreIncomplete = !active && !loaded.complete
                            if (!active || !owner || !validateHost(owner.host).ok) {
                                active = undefined
                                clearSession()
                                set({ ...SIGNED_OUT_ACCOUNT, accounts, activeAccountKey: null, unreadableAccountKeys })
                                return
                            }
                            set({
                                ...(active.user ? mirrorOf(active) : SIGNED_OUT_ACCOUNT),
                                accounts: withAccount(accounts, { ...active, lastUsedAt: now }),
                                activeAccountKey: active.key,
                                unreadableAccountKeys,
                                status: 'loading',
                                signedIn: false,
                                host: owner.host,
                                clientId: owner.clientId,
                                method: owner.method,
                                region: regionForHost(owner.host),
                            })
                            const tokens = getSessionTokens()
                            let refreshedDuringRestore = false
                            if (
                                tokens?.kind === 'oauth' &&
                                tokens.expiresAt !== null &&
                                tokens.expiresAt - Date.now() < RESTORE_REFRESH_MARGIN_MS
                            ) {
                                refreshedDuringRestore = true
                                try {
                                    if ((await refreshAccessToken()) === null) {
                                        return
                                    }
                                } catch {
                                    // Offline or a server error: keep the session. The next 401 retries the refresh.
                                }
                            }
                            const { user } = get()
                            if (!user) {
                                await get().reloadAccount()
                            }
                            set({ status: 'signed_in', signedIn: true })
                            if (!refreshedDuringRestore && AppState.currentState === 'active') {
                                refreshBeforeForegroundMargin()
                            }
                            const restored = get().user
                            if (restored) {
                                identify(restored.distinctId)
                            }
                            track('mobile_session_restored', { method: get().method })
                            if (user) {
                                void get().reloadAccount()
                            }
                        } finally {
                            if (!restoreIncomplete) {
                                const { status, activeAccountKey } = get()
                                settleLaunch(
                                    active && status === 'signed_in' && activeAccountKey === active.key
                                        ? refOf(active)
                                        : null
                                )
                            }
                        }
                    })()
                    return restoring
                },

                signIn: async (host, clientId, options) => {
                    const validation = validateHost(host)
                    if (!validation.ok) {
                        throw new SignInInputError(validation.error)
                    }
                    const trimmedClientId = clientId.trim()
                    if (!trimmedClientId) {
                        throw new SignInInputError('Enter the OAuth client ID of the PostHog app on this instance.')
                    }
                    const intent = ++signInIntent
                    if (get().status === 'signed_out') {
                        await retryRestore()
                        if (get().status === 'signed_in') {
                            return
                        }
                    }
                    const { accounts, freshLoginNext, unreadableAccountKeys } = get()
                    const { tokens, ...browser } = await authorize({
                        host: validation.host,
                        clientId: trimmedClientId,
                        // A usable account has its web session in the browser, which would return it again.
                        preferEphemeralSession:
                            options?.freshLogin === true ||
                            freshLoginNext ||
                            accounts.some(
                                (account) => account.key !== options?.reauth && isUsable(account, unreadableAccountKeys)
                            ),
                    })
                    const ownership = { kept: false }
                    try {
                        await completeSignIn(
                            tokens,
                            'oauth',
                            validation.host,
                            trimmedClientId,
                            intent,
                            options?.reauth,
                            browser,
                            ownership
                        )
                    } catch (error) {
                        if (tokens.refreshToken && !ownership.kept) {
                            void revokeToken({
                                host: validation.host,
                                clientId: trimmedClientId,
                                token: tokens.refreshToken,
                            })
                        }
                        throw error
                    }
                },

                signInWithPersonalApiKey: async (host, key) => {
                    if (!__DEV__) {
                        throw new SignInInputError('Personal API keys only work in development builds.')
                    }
                    const validation = validateHost(host)
                    if (!validation.ok) {
                        throw new SignInInputError(validation.error)
                    }
                    const trimmedKey = key.trim()
                    if (!trimmedKey) {
                        throw new SignInInputError('Paste a personal API key.')
                    }
                    const intent = ++signInIntent
                    await completeSignIn(
                        {
                            kind: 'personal_api_key',
                            accessToken: trimmedKey,
                            refreshToken: null,
                            expiresAt: null,
                            grantedScopes: null,
                            requestedScopes: null,
                        },
                        'personal_api_key',
                        validation.host,
                        null,
                        intent,
                        undefined,
                        { privateSession: false, selectAccount: false },
                        { kept: false }
                    )
                },

                selectProject: (projectId, from) => {
                    changeProject(projectId, from)
                },

                reloadAccount: () => {
                    const session = sessionGeneration()
                    if (reloading?.session === session) {
                        return reloading.promise
                    }
                    const promise = (async (): Promise<void> => {
                        if (get().status === 'signed_out') {
                            return
                        }
                        set({ accountLoading: true })
                        try {
                            const account = await loadAccount()
                            // The account belongs to the earlier session. The new session loads its own.
                            if (sessionGeneration() !== session) {
                                return
                            }
                            const before = get().projectId
                            setActive(accountFields(account, before))
                            if (before !== null && get().projectId !== before) {
                                void queryClient.resetQueries()
                            }
                            set({ accountLoading: false })
                        } catch (error) {
                            // The failure belongs to the earlier session, so it must not show on the new one.
                            if (sessionGeneration() !== session) {
                                return
                            }
                            if (error instanceof NotSignedInError) {
                                set({ accountLoading: false })
                                return
                            }
                            set({
                                accountLoading: false,
                                accountError: accountLoadMessage(error, get().method ?? 'oauth'),
                            })
                            track('mobile_account_reload_failed', { reason: accountLoadKind(error) })
                        }
                    })().finally(() => {
                        if (reloading?.promise === promise) {
                            reloading = null
                        }
                    })
                    reloading = { session, promise }
                    return promise
                },

                updateOrganizations: (update) => {
                    setActive({ organizations: update(get().organizations) })
                },

                switchAccount: async (key, { projectId, from }) => {
                    const intent = ++signInIntent
                    await serializeSessionTransition(async () => {
                        const state = get()
                        const target = state.accounts.find((account) => account.key === key)
                        if (!target) {
                            throw new Error('This account is no longer on this device.')
                        }
                        if (state.activeAccountKey === key && state.status === 'signed_in') {
                            if (projectId !== undefined) {
                                changeProject(projectId, from)
                            }
                            return
                        }
                        await switchTo(target, { projectId, from, canPublish: () => intent === signInIntent })
                    })
                },

                signOut: async () => {
                    ++signInIntent
                    await serializeSessionTransition(() => signOutActive(true))
                },

                signOutAccount: async (key) => {
                    if (key === get().activeAccountKey) {
                        await get().signOut()
                        return
                    }
                    await serializeSessionTransition(async () => {
                        const account = get().accounts.find((candidate) => candidate.key === key)
                        if (!account) {
                            return
                        }
                        if (key === get().activeAccountKey) {
                            await signOutActive(true)
                            return
                        }
                        await signOutInactive(account)
                    })
                },

                signOutAll: async () => {
                    ++signInIntent
                    await serializeSessionTransition(async () => {
                        await signOutActive(false)
                        for (const account of get().accounts) {
                            await signOutInactive(account)
                        }
                    })
                },
            }
        },
        {
            name: 'posthog-mobile-auth',
            version: 2,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state): PersistedAuth => ({
                region: state.region,
                host: state.host,
                clientId: state.clientId,
                method: state.method,
                user: state.user,
                organizations: state.organizations,
                projects: state.projects,
                projectId: state.projectId,
                projectName: state.projectName,
                signedOutReason: state.signedOutReason,
                expiredAccountKey: state.expiredAccountKey,
                accounts: state.accounts,
                activeAccountKey: state.activeAccountKey,
                freshLoginNext: state.freshLoginNext,
                pendingSlotRemovals: state.pendingSlotRemovals,
            }),
            // Version 1 held one account in the session fields. Restore turns them into that account's entry once it
            // has read the slot they belong to.
            migrate: (persisted, version) =>
                version === 1 && typeof persisted === 'object' && persisted !== null
                    ? {
                          ...(persisted as Partial<PersistedAuth>),
                          accounts: [],
                          activeAccountKey: null,
                          freshLoginNext: false,
                      }
                    : {},
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

function waitForHydration(): Promise<void> {
    return hydration.wait()
}

/** Deletes the slots whose removal failed, before launch reads them, and revokes the tokens it can read. */
async function finishSlotRemovals(): Promise<void> {
    for (const key of useAuthStore.getState().pendingSlotRemovals) {
        const read = await readAccountSession(key)
        if (!(await forgetAccountSlot(key))) {
            continue
        }
        if (read.kind === 'ok') {
            revokeStored(read.session)
        }
        useAuthStore.setState((state) => ({ pendingSlotRemovals: without(state.pendingSlotRemovals, key) }))
    }
}

/** Runs restore again after a launch that could not read storage, such as one before the first unlock. */
async function retryRestore(): Promise<void> {
    const due = (): boolean => restoreIncomplete && useAuthStore.getState().status === 'signed_out'
    if (!due()) {
        return
    }
    await serializeSessionTransition(async () => {
        if (!due()) {
            return
        }
        restoring = null
        await useAuthStore.getState().restore()
    })
}

/**
 * Ends the active session: its requests, its slot, its metadata (kept for an expiry, so the list shows it needs a
 * sign-in), the in-memory caches and its persisted data. `then` is the status to leave, `loading` while another
 * account follows.
 */
async function endActiveSession(
    reason: 'user' | 'expired',
    then: 'signed_out' | 'loading' = 'signed_out'
): Promise<void> {
    const state = useAuthStore.getState()
    const key = getSessionAccountKey() ?? state.activeAccountKey
    const owner = getSessionIdentity()
    const account = state.accounts.find((candidate) => candidate.key === key)
    const removed: AccountRef | null =
        key && owner ? { key, host: owner.host, userUuid: owner.userUuid } : account ? refOf(account) : null
    // Before the reset, so the events belong to the user who signed out.
    track('mobile_signed_out', { reason, method: state.method })
    if (reason === 'user' && account) {
        track('mobile_account_removed', { account_count: state.accounts.length - 1, region: account.region })
    }
    await endSessionRequests()
    reloading = null
    refreshing = null
    clearSession()
    const ended = sessionGeneration()
    const forgotten = key ? await forgetAccountSlot(key) : true
    queryClient.clear()
    resetAnalytics()
    await runTasks(sessionEndTasks)
    if (removed) {
        await runTasks(accountRemovedTasks, removed)
    }
    useAuthStore.setState((current) => ({
        accounts: !key
            ? current.accounts
            : reason === 'expired'
              ? markNeedsSignIn(current.accounts, key)
              : current.accounts.filter((candidate) => candidate.key !== key),
        pendingSlotRemovals:
            key && !forgotten ? [...without(current.pendingSlotRemovals, key), key] : current.pendingSlotRemovals,
        // A switch that started while the cleanup ran owns the session fields now.
        ...(sessionGeneration() === ended
            ? {
                  ...SIGNED_OUT_ACCOUNT,
                  status: then,
                  activeAccountKey: null,
                  signedOutReason: reason === 'expired' ? 'expired' : null,
                  expiredAccountKey: reason === 'expired' ? key : null,
              }
            : {}),
    }))
}

/**
 * Handles credentials the server refused. While they are still the session's, the session ends as expired and no other
 * account becomes active, so the user sees what happened. When a switch left them behind, only their account is marked.
 */
async function expireCredentials(key: string, failed: SessionTokens, session: number): Promise<void> {
    const work = async (): Promise<void> => {
        if (sessionGeneration() === session && getSessionAccountKey() === key) {
            await endActiveSession('expired')
            return
        }
        const read = await readAccountSession(key)
        if (read.kind === 'ok' && sameCredentials(read.session.tokens, failed)) {
            const forgotten = await forgetAccountSlot(key)
            const account = useAuthStore.getState().accounts.find((candidate) => candidate.key === key)
            useAuthStore.setState((current) => ({
                accounts: markNeedsSignIn(current.accounts, key),
                pendingSlotRemovals: forgotten
                    ? current.pendingSlotRemovals
                    : [...without(current.pendingSlotRemovals, key), key],
            }))
            if (account) {
                await runTasks(accountRemovedTasks, refOf(account))
            }
        }
    }
    // A transition can be waiting on the request that found the expiry, so waiting for the queue here would deadlock.
    if (transitionsRunning > 0) {
        void serializeSessionTransition(work).catch(() => undefined)
        return
    }
    await serializeSessionTransition(work)
}

async function refreshOnce(): Promise<string | null> {
    const session = sessionGeneration()
    const key = getSessionAccountKey()
    const owner = getSessionIdentity()
    const tokens = getSessionTokens()
    // A 401 during sign in means the new credentials are bad. Sign in reports that itself.
    if (useAuthStore.getState().status === 'signed_out' || !tokens || !owner || !key) {
        return null
    }
    if (!tokens.refreshToken || !owner.clientId) {
        await expireCredentials(key, tokens, session)
        return null
    }
    // The refresh goes to the host and client the token belongs to, whatever the session fields show by then.
    const { host, clientId } = owner
    const used = tokens.refreshToken
    let next: SessionTokens
    try {
        next = await refreshTokens({
            host,
            clientId,
            refreshToken: used,
            grantedScopes: tokens.grantedScopes,
            requestedScopes: tokens.requestedScopes,
        })
    } catch (error) {
        if (error instanceof OAuthError && error.kind === 'session_expired') {
            await expireCredentials(key, tokens, session)
            return null
        }
        // A failure that belongs to an earlier session says nothing about the current one.
        if (sessionGeneration() !== session) {
            return null
        }
        if (error instanceof OAuthError && error.kind === 'network') {
            throw new TransportError()
        }
        throw error
    }
    const saved = await saveRefreshedTokens({ key, owner, used, tokens: next })
    if (saved === 'gone') {
        // The account left the device or signed in again while the refresh was in flight. The rotated refresh token
        // is valid at its host but stored nowhere, so revoke it there.
        revokeStored({ tokens: next, identity: owner })
    }
    // A session that changed while the refresh was in flight gets no token: the caller sends it to the earlier host.
    return saved === 'session' && sessionGeneration() === session ? next.accessToken : null
}

// Concurrent callers share one request, because each refresh rotates the token and a second request with the old
// one would race it. A caller from a later session never joins, because the earlier refresh returns no token.
export function refreshAccessToken(): Promise<string | null> {
    const session = sessionGeneration()
    if (refreshing?.session === session) {
        return refreshing.promise
    }
    const key = getSessionAccountKey()
    const promise = refreshOnce().finally(() => {
        if (refreshing?.promise === promise) {
            refreshing = null
        }
        if (key && accountRefreshes.get(key) === promise) {
            accountRefreshes.delete(key)
        }
    })
    refreshing = { session, promise }
    if (key) {
        accountRefreshes.set(key, promise)
    }
    return promise
}

function refreshBeforeForegroundMargin(): void {
    const tokens = getSessionTokens()
    if (
        useAuthStore.getState().status !== 'signed_in' ||
        tokens?.kind !== 'oauth' ||
        tokens.expiresAt === null ||
        tokens.expiresAt - Date.now() >= FOREGROUND_REFRESH_MARGIN_MS
    ) {
        return
    }
    // Offline or a server error keeps the session; the next foreground or 401 tries again.
    refreshAccessToken().catch(() => undefined)
}

let foregroundSubscription: NativeEventSubscription | null = null

export function installAuthProvider(): void {
    foregroundSubscription?.remove()
    foregroundSubscription = AppState.addEventListener('change', (state) => {
        if (state === 'active') {
            refreshBeforeForegroundMargin()
            void retryRestore()
        }
    })
    setAuthProvider({
        getAuth: () => {
            const state = useAuthStore.getState()
            const host = state.host ?? ''
            const owner = getSessionIdentity()
            // A token works only at its owner's host. While the session fields show another host, no request gets it.
            const accessToken = owner && owner.host !== host ? null : (getSessionTokens()?.accessToken ?? null)
            return {
                host,
                accessToken,
                projectId: state.projectId,
                session: sessionGeneration(),
            }
        },
        refreshAccessToken,
    })
}

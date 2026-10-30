import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { ApiError, NotSignedInError, setAuthProvider } from '@/api/client'
import { queryClient } from '@/api/queryClient'
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
import { authorize, OAuthError, refreshTokens, revokeToken } from './oauth'
import { type RegionId, regionForHost, validateHost } from './regions'
import { AccountLoadError, accountLoadKind, SignInInputError } from './signInErrors'
import {
    clearTokens,
    commitSessionTokens,
    getSessionIdentity,
    getSessionTokens,
    loadTokens,
    type SessionTokens,
    saveRefreshedTokens,
    sessionGeneration,
    setSessionTokens,
} from './tokens'

export type { AuthOrganization, AuthProject, AuthUser } from './account'

export type AuthStatus = 'loading' | 'signed_out' | 'signed_in'
export type AuthMethod = 'oauth' | 'personal_api_key'
export type ProjectSwitchSource = 'nav_menu' | 'settings' | 'push'

export interface AuthState {
    status: AuthStatus
    signedIn: boolean
    /** The region of the last sign-in. Kept after sign out so the sign-in screen starts there. */
    region: RegionId
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
    restore: () => Promise<void>
    signIn: (host: string, clientId: string) => Promise<void>
    /** Development builds only. The personal API key never refreshes. */
    signInWithPersonalApiKey: (host: string, key: string) => Promise<void>
    selectProject: (projectId: number, from: ProjectSwitchSource) => void
    reloadAccount: () => Promise<void>
    signOut: () => Promise<void>
}

/** Refresh at launch when the access token has less than this left, so the first requests do not all 401. */
const RESTORE_REFRESH_MARGIN_MS = 60_000

type SignOutTask = () => Promise<undefined | (() => void)>
type SessionEndTask = () => void | Promise<void>

const signOutTasks = new Set<SignOutTask>()
const sessionEndTasks = new Set<SessionEndTask>()

/** Registers work that must run while the session is still valid, before sign out drops the token. */
export function addSignOutTask(task: SignOutTask): () => void {
    signOutTasks.add(task)
    return () => {
        signOutTasks.delete(task)
    }
}

/**
 * Registers device cleanup for every end of a session: sign out and a session that expired. It runs after the token
 * is gone, so it must not call the API. Features use it to drop per-user state without the auth store importing them.
 */
export function addSessionEndTask(task: SessionEndTask): () => void {
    sessionEndTasks.add(task)
    return () => {
        sessionEndTasks.delete(task)
    }
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
    if (error instanceof TypeError) {
        return "Couldn't reach PostHog. Check your connection and try again."
    }
    return toError(error).message
}

/** In-flight work that callers of one session share. A caller from another session starts its own. */
interface SessionTask<T> {
    session: number
    promise: Promise<T>
}

let restoring: Promise<void> | null = null
let reloading: SessionTask<void> | null = null
let refreshing: SessionTask<string | null> | null = null
let signInIntent = 0
let sessionTransitions: Promise<void> = Promise.resolve()
const hydration = createPersistHydrationGate()

function serializeSessionTransition<T>(work: () => Promise<T>): Promise<T> {
    const result = sessionTransitions.then(work, work)
    sessionTransitions = result.then(
        () => undefined,
        () => undefined
    )
    return result
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

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => {
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

            const applyAccount = (account: Account, preferProjectId: number | null): void => {
                set(accountFields(account, preferProjectId))
            }

            const completeSignIn = async (
                tokens: SessionTokens,
                method: AuthMethod,
                host: string,
                clientId: string | null,
                intent: number
            ): Promise<void> => {
                let account: Account
                try {
                    account = await loadAccountWithCredentials(host, tokens.accessToken)
                } catch (error) {
                    throw new AccountLoadError(accountLoadKind(error), accountLoadMessage(error, method))
                }
                await serializeSessionTransition(async () => {
                    if (intent !== signInIntent) {
                        throw new OAuthError('cancelled')
                    }
                    const previous = get()
                    const previousSession = sessionGeneration()
                    let recoveries: (() => void)[] = []
                    if (previous.status === 'signed_in') {
                        recoveries = await runSignOutTasks()
                    }
                    try {
                        if (intent !== signInIntent) {
                            throw new OAuthError('cancelled')
                        }
                        if (previous.status === 'signed_in') {
                            await Promise.allSettled([...sessionEndTasks].map(async (task) => task()))
                        }
                        const previousTokens = getSessionTokens()
                        const region = regionForHost(host)
                        const committed = await commitSessionTokens(
                            tokens,
                            { host, clientId, method, userUuid: account.user.uuid },
                            () => intent === signInIntent && sessionGeneration() === previousSession,
                            () => {
                                queryClient.clear()
                                const preferProjectId =
                                    previous.user?.uuid === account.user.uuid ? previous.projectId : null
                                set({
                                    ...accountFields(account, preferProjectId),
                                    status: 'signed_in',
                                    signedIn: true,
                                    region,
                                    host,
                                    clientId,
                                    method,
                                    signedOutReason: null,
                                })
                            }
                        )
                        if (!committed) {
                            throw new OAuthError('cancelled')
                        }
                        if (previous.status === 'signed_in') {
                            queryClient.clear()
                        }
                        identify(account.user.distinctId)
                        track('mobile_signed_in', { method, region })
                        if (
                            previousTokens?.kind === 'oauth' &&
                            previousTokens.refreshToken &&
                            previous.host &&
                            previous.clientId
                        ) {
                            void revokeToken({
                                host: previous.host,
                                clientId: previous.clientId,
                                token: previousTokens.refreshToken,
                            })
                        }
                    } catch (error) {
                        if (sessionGeneration() === previousSession) {
                            for (const recover of recoveries) {
                                recover()
                            }
                        }
                        throw error
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

                restore: () => {
                    restoring ??= (async () => {
                        await waitForHydration()
                        const tokens = await loadTokens()
                        const owner = getSessionIdentity()
                        if (!tokens || !owner || !validateHost(owner.host).ok) {
                            setSessionTokens(null)
                            set(SIGNED_OUT_ACCOUNT)
                            return
                        }
                        const metadata = get()
                        const sameAccount =
                            metadata.host === owner.host &&
                            metadata.clientId === owner.clientId &&
                            metadata.method === owner.method &&
                            metadata.user?.uuid === owner.userUuid
                        set({
                            ...(!sameAccount ? SIGNED_OUT_ACCOUNT : {}),
                            status: 'loading',
                            signedIn: false,
                            host: owner.host,
                            clientId: owner.clientId,
                            method: owner.method,
                            region: regionForHost(owner.host),
                        })
                        if (
                            tokens.kind === 'oauth' &&
                            tokens.expiresAt !== null &&
                            tokens.expiresAt - Date.now() < RESTORE_REFRESH_MARGIN_MS
                        ) {
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
                        const restored = get().user
                        if (restored) {
                            identify(restored.distinctId)
                        }
                        track('mobile_session_restored', { method: get().method })
                        if (user) {
                            void get().reloadAccount()
                        }
                    })()
                    return restoring
                },

                signIn: async (host, clientId) => {
                    const validation = validateHost(host)
                    if (!validation.ok) {
                        throw new SignInInputError(validation.error)
                    }
                    const trimmedClientId = clientId.trim()
                    if (!trimmedClientId) {
                        throw new SignInInputError('Enter the OAuth client ID of the PostHog app on this instance.')
                    }
                    const intent = ++signInIntent
                    const tokens = await authorize({ host: validation.host, clientId: trimmedClientId })
                    try {
                        await completeSignIn(tokens, 'oauth', validation.host, trimmedClientId, intent)
                    } catch (error) {
                        if (tokens.refreshToken) {
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
                        intent
                    )
                },

                selectProject: (projectId, from) => {
                    const { projects, projectId: current } = get()
                    const project = projects.find((candidate) => candidate.id === projectId)
                    if (!project || projectId === current) {
                        return
                    }
                    set({ projectId, projectName: project.name })
                    track('mobile_project_switched', { from })
                    // Every cached query belongs to the previous project. Reset drops the data, so no
                    // screen shows the old project's reports, and refetches what is on screen.
                    void queryClient.resetQueries()
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
                            applyAccount(account, before)
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

                signOut: async () => {
                    ++signInIntent
                    await serializeSessionTransition(async () => {
                        const { host, clientId, status } = get()
                        if (status === 'signed_out') {
                            return
                        }
                        if (status === 'signed_in') {
                            await runSignOutTasks()
                        }
                        const tokens = getSessionTokens()
                        if (tokens?.kind === 'oauth' && tokens.refreshToken && host && clientId) {
                            await revokeToken({ host, clientId, token: tokens.refreshToken })
                        }
                        await endSession('user')
                    })
                },
            }
        },
        {
            name: 'posthog-mobile-auth',
            version: 1,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({
                region: state.region,
                host: state.host,
                clientId: state.clientId,
                method: state.method,
                user: state.user,
                organizations: state.organizations,
                projects: state.projects,
                projectId: state.projectId,
                projectName: state.projectName,
            }),
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

function waitForHydration(): Promise<void> {
    return hydration.wait()
}

async function endSession(reason: 'user' | 'expired'): Promise<void> {
    // Before the reset, so the event belongs to the user who signed out.
    track('mobile_signed_out', { reason, method: useAuthStore.getState().method })
    reloading = null
    refreshing = null
    await clearTokens()
    queryClient.clear()
    resetAnalytics()
    await Promise.allSettled([...sessionEndTasks].map(async (task) => task()))
    useAuthStore.setState({ ...SIGNED_OUT_ACCOUNT, signedOutReason: reason === 'expired' ? 'expired' : null })
}

async function refreshOnce(): Promise<string | null> {
    const session = sessionGeneration()
    const { status, host, clientId } = useAuthStore.getState()
    const tokens = getSessionTokens()
    // A 401 during sign in means the new credentials are bad. Sign in reports that itself.
    if (status === 'signed_out' || !tokens) {
        return null
    }
    if (!tokens.refreshToken || !host || !clientId) {
        await endSession('expired')
        return null
    }
    let next: SessionTokens
    try {
        next = await refreshTokens({
            host,
            clientId,
            refreshToken: tokens.refreshToken,
            grantedScopes: tokens.grantedScopes,
            requestedScopes: tokens.requestedScopes,
        })
    } catch (error) {
        // A rejection from the earlier host says nothing about the current session, so it must not end it.
        if (sessionGeneration() !== session) {
            return null
        }
        if (error instanceof OAuthError && error.kind === 'session_expired') {
            await endSession('expired')
            return null
        }
        throw error
    }
    if (sessionGeneration() !== session) {
        // The user signed out or in again while the refresh was in flight. The caller sends the result to the
        // earlier host, so it gets no token. The rotated refresh token is valid at that host but stored nowhere,
        // so revoke it there.
        if (next.refreshToken) {
            void revokeToken({ host, clientId, token: next.refreshToken })
        }
        return null
    }
    return (await saveRefreshedTokens(next, session)) ? next.accessToken : null
}

// Concurrent callers share one request, because each refresh rotates the token and a second request with the old
// one would race it. A caller from a later session never joins, because the earlier refresh returns no token.
export function refreshAccessToken(): Promise<string | null> {
    const session = sessionGeneration()
    if (refreshing?.session === session) {
        return refreshing.promise
    }
    const promise = refreshOnce().finally(() => {
        if (refreshing?.promise === promise) {
            refreshing = null
        }
    })
    refreshing = { session, promise }
    return promise
}

export function installAuthProvider(): void {
    setAuthProvider({
        getAuth: () => {
            const state = useAuthStore.getState()
            return {
                host: state.host ?? '',
                accessToken: getSessionTokens()?.accessToken ?? null,
                projectId: state.projectId,
                session: sessionGeneration(),
            }
        },
        refreshAccessToken,
    })
}

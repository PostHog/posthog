import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { ApiError, NotSignedInError, setAuthProvider } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { identify, resetAnalytics, track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { sleep } from '@/lib/sleep'

import {
    type Account,
    type AuthOrganization,
    type AuthProject,
    type AuthUser,
    loadAccount,
    pickProjectId,
} from './account'
import { authorize, OAuthError, refreshTokens, revokeToken } from './oauth'
import { type RegionId, regionForHost, validateHost } from './regions'
import { AccountLoadError, accountLoadKind, SignInInputError } from './signInErrors'
import { clearTokens, getSessionTokens, loadTokens, type SessionTokens, saveTokens, setSessionTokens } from './tokens'

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

const SIGN_OUT_TASK_TIMEOUT_MS = 5_000
/** Refresh at launch when the access token has less than this left, so the first requests do not all 401. */
const RESTORE_REFRESH_MARGIN_MS = 60_000

type SignOutTask = () => Promise<void>
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

let restoring: Promise<void> | null = null
let reloading: Promise<void> | null = null
let refreshing: Promise<string | null> | null = null

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => {
            const applyAccount = (account: Account, preferProjectId: number | null): void => {
                const projectId = pickProjectId(account.projects, [preferProjectId, account.webTeamId])
                set({
                    user: account.user,
                    organizations: account.organizations,
                    projects: account.projects,
                    projectId,
                    projectName: projectNameFor(account.projects, projectId),
                    accountError: null,
                })
            }

            const completeSignIn = async (tokens: SessionTokens, method: AuthMethod): Promise<void> => {
                setSessionTokens(tokens)
                let account: Account
                try {
                    account = await loadAccount()
                } catch (error) {
                    setSessionTokens(null)
                    throw new AccountLoadError(accountLoadKind(error), accountLoadMessage(error, method))
                }
                await saveTokens(tokens)
                const previous = get().user
                // Reopen the project this user had last, but never carry one over from another user.
                applyAccount(account, previous?.uuid === account.user.uuid ? get().projectId : null)
                set({ status: 'signed_in', signedIn: true, method, signedOutReason: null })
                identify(account.user.distinctId)
                track('mobile_signed_in', { method, region: get().region })
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
                        const { host } = get()
                        if (!tokens || !host) {
                            setSessionTokens(null)
                            set(SIGNED_OUT_ACCOUNT)
                            return
                        }
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
                    set({
                        region: regionForHost(validation.host),
                        host: validation.host,
                        clientId: trimmedClientId,
                        signedOutReason: null,
                    })
                    const tokens = await authorize({ host: validation.host, clientId: trimmedClientId })
                    try {
                        await completeSignIn(tokens, 'oauth')
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
                    set({ region: regionForHost(validation.host), host: validation.host, signedOutReason: null })
                    await completeSignIn(
                        {
                            kind: 'personal_api_key',
                            accessToken: trimmedKey,
                            refreshToken: null,
                            expiresAt: null,
                            grantedScopes: null,
                            requestedScopes: null,
                        },
                        'personal_api_key'
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
                    reloading ??= (async () => {
                        if (get().status === 'signed_out') {
                            return
                        }
                        set({ accountLoading: true })
                        try {
                            const account = await loadAccount()
                            const before = get().projectId
                            applyAccount(account, before)
                            if (before !== null && get().projectId !== before) {
                                void queryClient.resetQueries()
                            }
                            set({ accountLoading: false })
                        } catch (error) {
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
                        reloading = null
                    })
                    return reloading
                },

                signOut: async () => {
                    const { host, clientId, status } = get()
                    const tokens = getSessionTokens()
                    if (status === 'signed_in' && signOutTasks.size > 0) {
                        await Promise.race([
                            Promise.allSettled([...signOutTasks].map((task) => task())),
                            sleep(SIGN_OUT_TASK_TIMEOUT_MS),
                        ])
                    }
                    if (tokens?.kind === 'oauth' && tokens.refreshToken && host && clientId) {
                        await revokeToken({ host, clientId, token: tokens.refreshToken })
                    }
                    await endSession('user')
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
        }
    )
)

function waitForHydration(): Promise<void> {
    if (useAuthStore.persist.hasHydrated()) {
        return Promise.resolve()
    }
    return new Promise((resolve) => {
        const unsubscribe = useAuthStore.persist.onFinishHydration(() => {
            unsubscribe()
            resolve()
        })
    })
}

async function endSession(reason: 'user' | 'expired'): Promise<void> {
    // Before the reset, so the event belongs to the user who signed out.
    track('mobile_signed_out', { reason, method: useAuthStore.getState().method })
    await clearTokens()
    queryClient.clear()
    resetAnalytics()
    await Promise.allSettled([...sessionEndTasks].map(async (task) => task()))
    useAuthStore.setState({ ...SIGNED_OUT_ACCOUNT, signedOutReason: reason === 'expired' ? 'expired' : null })
}

async function refreshOnce(): Promise<string | null> {
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
        if (error instanceof OAuthError && error.kind === 'session_expired') {
            await endSession('expired')
            return null
        }
        throw error
    }
    if (getSessionTokens() !== tokens) {
        // The user signed out or in again while the refresh was in flight.
        return getSessionTokens()?.accessToken ?? null
    }
    await saveTokens(next)
    return next.accessToken
}

// Concurrent callers share one request, because each refresh rotates the token and a second request with the old
// one would race it.
export function refreshAccessToken(): Promise<string | null> {
    refreshing ??= refreshOnce().finally(() => {
        refreshing = null
    })
    return refreshing
}

export function installAuthProvider(): void {
    setAuthProvider({
        getAuth: () => {
            const state = useAuthStore.getState()
            return {
                host: state.host ?? '',
                accessToken: getSessionTokens()?.accessToken ?? null,
                projectId: state.projectId,
            }
        },
        refreshAccessToken,
    })
}

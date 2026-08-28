import { LogicWrapper, MakeLogicType, actions, kea, path, reducers } from 'kea'

// This records viewer consent, not a source-validation verdict. The full rationale lives in
// docs/internal/generated-notebook-widgets.md#generated-code-trust-model.

const MAX_TRUSTED_BUILD_HASHES = 500
const BUILD_HASH_PATTERN = /^[a-f0-9]{64}$/

type WidgetTrustScopes = {
    buildHashes: string[]
    notebookKeys: string[]
    projectIds: number[]
}

type WidgetTrustByUser = Record<string, WidgetTrustScopes>

export type NotebookWidgetTrust = {
    buildTrusted: boolean
    notebookTrusted: boolean
    projectTrusted: boolean
}

interface notebookWidgetTrustLogicValues {
    sessionBuildHashes: string[]
    trustByUser: WidgetTrustByUser
}

interface notebookWidgetTrustLogicActions {
    setNotebookTrusted: (
        userId: number,
        projectId: number,
        notebookShortId: string,
        trusted: boolean
    ) => { userId: number; projectId: number; notebookShortId: string; trusted: boolean }
    setProjectTrusted: (
        userId: number,
        projectId: number,
        trusted: boolean
    ) => { userId: number; projectId: number; trusted: boolean }
    trustBuild: (userId: number | null, buildHash: string) => { userId: number | null; buildHash: string }
}

type notebookWidgetTrustLogicType = MakeLogicType<notebookWidgetTrustLogicValues, notebookWidgetTrustLogicActions>

const EMPTY_TRUST_SCOPES: WidgetTrustScopes = {
    buildHashes: [],
    notebookKeys: [],
    projectIds: [],
}

function notebookKey(projectId: number, notebookShortId: string): string {
    return `${projectId}:${notebookShortId}`
}

function scopesForUser(trustByUser: WidgetTrustByUser, userId: number): WidgetTrustScopes {
    const scopes = trustByUser[String(userId)]
    return scopes &&
        Array.isArray(scopes.buildHashes) &&
        Array.isArray(scopes.notebookKeys) &&
        Array.isArray(scopes.projectIds)
        ? scopes
        : EMPTY_TRUST_SCOPES
}

function setMembership<T>(values: T[], value: T, included: boolean, maxLength?: number): T[] {
    const withoutValue = values.filter((candidate) => candidate !== value)
    if (!included) {
        return withoutValue
    }
    const next = [...withoutValue, value]
    return maxLength ? next.slice(-maxLength) : next
}

export function getNotebookWidgetTrust({
    trustByUser,
    sessionBuildHashes,
    userId,
    projectId,
    notebookShortId,
    buildHash,
}: {
    trustByUser: WidgetTrustByUser
    sessionBuildHashes: string[]
    userId: number | null
    projectId: number | null
    notebookShortId: string
    buildHash: string | null
}): NotebookWidgetTrust {
    const validBuildHash = buildHash !== null && BUILD_HASH_PATTERN.test(buildHash)
    const scopes = userId === null ? EMPTY_TRUST_SCOPES : scopesForUser(trustByUser, userId)
    const projectTrusted = projectId !== null && scopes.projectIds.includes(projectId)
    const notebookTrusted = projectId !== null && scopes.notebookKeys.includes(notebookKey(projectId, notebookShortId))
    return {
        buildTrusted:
            validBuildHash &&
            (sessionBuildHashes.includes(buildHash) ||
                scopes.buildHashes.includes(buildHash) ||
                notebookTrusted ||
                projectTrusted),
        notebookTrusted,
        projectTrusted,
    }
}

export const notebookWidgetTrustLogic: LogicWrapper<notebookWidgetTrustLogicType> = kea<notebookWidgetTrustLogicType>([
    path(['products', 'notebooks', 'notebookWidgetTrustLogic']),
    actions({
        setNotebookTrusted: (userId: number, projectId: number, notebookShortId: string, trusted: boolean) => ({
            userId,
            projectId,
            notebookShortId,
            trusted,
        }),
        setProjectTrusted: (userId: number, projectId: number, trusted: boolean) => ({
            userId,
            projectId,
            trusted,
        }),
        trustBuild: (userId: number | null, buildHash: string) => ({ userId, buildHash }),
    }),
    reducers({
        sessionBuildHashes: [
            [] as string[],
            {
                trustBuild: (state, { userId, buildHash }) =>
                    userId === null && BUILD_HASH_PATTERN.test(buildHash)
                        ? setMembership(state, buildHash, true, MAX_TRUSTED_BUILD_HASHES)
                        : state,
            },
        ],
        trustByUser: [
            {} as WidgetTrustByUser,
            { persist: true },
            {
                setNotebookTrusted: (state, { userId, projectId, notebookShortId, trusted }) => {
                    const userKey = String(userId)
                    const scopes = scopesForUser(state, userId)
                    return {
                        ...state,
                        [userKey]: {
                            ...scopes,
                            notebookKeys: setMembership(
                                scopes.notebookKeys,
                                notebookKey(projectId, notebookShortId),
                                trusted
                            ),
                        },
                    }
                },
                setProjectTrusted: (state, { userId, projectId, trusted }) => {
                    const userKey = String(userId)
                    const scopes = scopesForUser(state, userId)
                    return {
                        ...state,
                        [userKey]: {
                            ...scopes,
                            projectIds: setMembership(scopes.projectIds, projectId, trusted),
                        },
                    }
                },
                trustBuild: (state, { userId, buildHash }) => {
                    if (userId === null || !BUILD_HASH_PATTERN.test(buildHash)) {
                        return state
                    }
                    const userKey = String(userId)
                    const scopes = scopesForUser(state, userId)
                    return {
                        ...state,
                        [userKey]: {
                            ...scopes,
                            buildHashes: setMembership(scopes.buildHashes, buildHash, true, MAX_TRUSTED_BUILD_HASHES),
                        },
                    }
                },
            },
        ],
    }),
])

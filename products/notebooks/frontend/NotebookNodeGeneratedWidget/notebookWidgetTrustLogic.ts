import { LogicWrapper, MakeLogicType, actions, kea, path, reducers } from 'kea'

// This records viewer consent, not a source-validation verdict. The full rationale lives in
// docs/internal/generated-notebook-widgets.md#generated-code-trust-model.

const MAX_TRUSTED_BUILD_HASHES = 500
const BUILD_HASH_PATTERN = /^[a-f0-9]{64}$/

type WidgetTrustScopes = {
    buildHashes: string[]
}

type WidgetTrustByUser = Record<string, WidgetTrustScopes>

export type NotebookWidgetTrust = {
    buildTrusted: boolean
}

interface notebookWidgetTrustLogicValues {
    sessionBuildHashes: string[]
    trustByUser: WidgetTrustByUser
}

interface notebookWidgetTrustLogicActions {
    trustBuild: (userId: number | null, buildHash: string) => { userId: number | null; buildHash: string }
}

type notebookWidgetTrustLogicType = MakeLogicType<notebookWidgetTrustLogicValues, notebookWidgetTrustLogicActions>

const EMPTY_TRUST_SCOPES: WidgetTrustScopes = {
    buildHashes: [],
}

function scopesForUser(trustByUser: WidgetTrustByUser, userId: number): WidgetTrustScopes {
    const scopes = trustByUser[String(userId)]
    return scopes && Array.isArray(scopes.buildHashes) ? scopes : EMPTY_TRUST_SCOPES
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
    buildHash,
}: {
    trustByUser: WidgetTrustByUser
    sessionBuildHashes: string[]
    userId: number | null
    buildHash: string | null
}): NotebookWidgetTrust {
    const validBuildHash = buildHash !== null && BUILD_HASH_PATTERN.test(buildHash)
    const scopes = userId === null ? EMPTY_TRUST_SCOPES : scopesForUser(trustByUser, userId)
    return {
        buildTrusted:
            validBuildHash &&
            ((userId === null && sessionBuildHashes.includes(buildHash)) || scopes.buildHashes.includes(buildHash)),
    }
}

export const notebookWidgetTrustLogic: LogicWrapper<notebookWidgetTrustLogicType> = kea<notebookWidgetTrustLogicType>([
    path(['products', 'notebooks', 'notebookWidgetTrustLogic']),
    actions({
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

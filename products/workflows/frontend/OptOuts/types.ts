export type OptOutEntry = {
    identifier: string
    source: string
    updated_at: string
}

export type OptOutPersonPreference = {
    identifier: string
    preferences: Record<string, boolean>
}

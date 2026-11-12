// A catalog entry that needs a hook names it with its version, `hook:<name>@<version>`, and a hog
// whose compiled-in hook has another version drops the entry. Each hook lists a hash of its source for
// every version it has had, so version N is the Nth hash. tests/unit/cli-catalog-hooks.test.ts fails
// until a changed source gets a new hash, and so a new version.
export const HOOK_SOURCE_HASHES: Record<string, readonly string[]> = {
    'dataWarehouse/viewGetHooks': ['6253b448a1b3'],
    'engineeringAnalytics/redactFailureLogsHooks': ['a8555081ec4e'],
    'experiments/createExperimentHooks': ['8d6b7735b62e'],
    'experiments/getExperimentHooks': ['79c8b4a2e561'],
    'experiments/listExperimentsHooks': ['039dcb062b79'],
    'experiments/updateExperimentHooks': ['dc26f14d64e9'],
    'featureFlags/conditionIdHooks': ['8715ed7c6985'],
    'featureFlags/updateFeatureFlagHooks': ['f668908fbf86'],
    'logs/groupByRedactionHooks': ['8758a390e643'],
    'logs/redactCredentialsHooks': ['c9ad8c9e56a8'],
    'replay/sessionRecordingGetHooks': ['c6c44d594f83'],
    'signals/inboxMySettingsHooks': ['3a11ff810aa0'],
    'workflows/broadcastLinkHooks': ['4ed62789d159'],
    'workflows/dataSuggestionCreateHooks': ['7f0b14e101aa'],
}

export function hookVersion(name: string): number | undefined {
    return HOOK_SOURCE_HASHES[name]?.length
}

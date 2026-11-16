import type { RowSelectionState } from '@tanstack/react-table'
import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'lib/posthog-typed'

import { releasesMergeCreate } from './generated/api'
import type { ReleaseDTOApi } from './generated/api.schemas'
import { releaseLogic } from './releaseLogic'
import { MergeCandidate, mergeCandidate, releaseToKeep } from './releaseMerge'
import { ReleaseRow } from './releaseUtils'

interface ReleaseMergeLogicValues {
    currentProjectId: number | null
    releases: ReleaseDTOApi[]
    rows: ReleaseRow[]
    canEditReleases: boolean
    selection: RowSelectionState
    mergeOpen: boolean
    keepId: string | null
    mergeName: string
    mergeNameEdited: boolean
    merging: boolean
    candidates: MergeCandidate[]
    hiddenReleaseIds: Set<string>
}

interface ReleaseMergeLogicActions {
    loadReleases: () => void
    setSelection: (selection: RowSelectionState) => { selection: RowSelectionState }
    setMergeOpen: (open: boolean) => { open: boolean }
    setKeepId: (keepId: string) => { keepId: string }
    setMergeName: (name: string) => { name: string }
    editMergeName: (name: string) => { name: string }
    mergeReleases: (keepId: string) => { keepId: string }
    mergeReleasesDone: () => { value: true }
}

type releaseMergeLogicType = MakeLogicType<ReleaseMergeLogicValues, ReleaseMergeLogicActions>

export const releaseMergeLogic = kea<releaseMergeLogicType>([
    path(['products', 'release', 'frontend', 'releaseMergeLogic']),
    connect(() => ({
        values: [releaseLogic, ['currentProjectId', 'releases', 'rows', 'canEditReleases']],
        actions: [releaseLogic, ['loadReleases']],
    })),
    actions({
        setSelection: (selection: RowSelectionState) => ({ selection }),
        setMergeOpen: (open: boolean) => ({ open }),
        setKeepId: (keepId: string) => ({ keepId }),
        setMergeName: (name: string) => ({ name }),
        editMergeName: (name: string) => ({ name }),
        mergeReleases: (keepId: string) => ({ keepId }),
        mergeReleasesDone: true,
    }),
    reducers({
        selection: [{} as RowSelectionState, { setSelection: (_, { selection }) => selection }],
        mergeOpen: [false, { setMergeOpen: (_, { open }) => open }],
        keepId: [null as string | null, { setKeepId: (_, { keepId }) => keepId }],
        mergeName: ['', { setMergeName: (_, { name }) => name, editMergeName: (_, { name }) => name }],
        mergeNameEdited: [false, { editMergeName: () => true, setMergeOpen: () => false }],
        merging: [false, { mergeReleases: () => true, mergeReleasesDone: () => false }],
    }),
    selectors({
        candidates: [
            (s) => [s.rows, s.releases, s.selection],
            (rows: ReleaseRow[], releases: ReleaseDTOApi[], selection: RowSelectionState): MergeCandidate[] => {
                const byId = new Map(releases.map((release) => [release.id, release]))
                return rows.filter((row) => selection[row.id]).map((row) => mergeCandidate(row, byId.get(row.id)))
            },
        ],
        hiddenReleaseIds: [
            (s) => [s.releases],
            (releases: ReleaseDTOApi[]): Set<string> =>
                new Set(releases.filter((release) => release.has_hidden_flags).map((release) => release.id)),
        ],
    }),
    listeners(({ actions, values }) => ({
        setMergeOpen: ({ open }) => {
            if (open) {
                const keepId = releaseToKeep(values.candidates)
                if (keepId) {
                    actions.setKeepId(keepId)
                }
                posthog.capture('release merge dialog opened', { count: values.candidates.length })
            }
        },
        setKeepId: ({ keepId }) => {
            const kept = values.candidates.find((candidate) => candidate.id === keepId)
            if (kept && !values.mergeNameEdited) {
                actions.setMergeName(kept.name)
            }
        },
        mergeReleases: async ({ keepId }) => {
            const sourceIds = values.candidates.map((candidate) => candidate.id).filter((id) => id !== keepId)
            try {
                const merged = await releasesMergeCreate(String(values.currentProjectId), keepId, {
                    release_ids: sourceIds,
                    name: values.mergeName.trim() || undefined,
                })
                lemonToast.success(`Merged ${sourceIds.length + 1} releases into ${merged.name}`)
                actions.setMergeOpen(false)
                actions.setSelection({})
                actions.loadReleases()
            } catch (error) {
                const detail = (error as { detail?: unknown }).detail
                lemonToast.error(
                    typeof detail === 'string' && detail ? detail : 'The releases could not be merged. Try again.'
                )
            } finally {
                actions.mergeReleasesDone()
            }
        },
    })),
])

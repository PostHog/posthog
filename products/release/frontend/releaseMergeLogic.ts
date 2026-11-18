import type { RowSelectionState } from '@tanstack/react-table'
import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'lib/posthog-typed'

import { releasesMergeCreate } from './generated/api'
import type { ReleaseDTOApi } from './generated/api.schemas'
import { releaseLogic } from './releaseLogic'
import { MergeCandidate, mergeCandidate, releaseToKeep } from './releaseMerge'
import { ReleaseRow, ReleaseStage } from './releaseUtils'

interface ReleaseMergeLogicValues {
    currentProjectId: number | null
    releases: ReleaseDTOApi[]
    rows: ReleaseRow[]
    canEditReleases: boolean
    selection: RowSelectionState
    mergeOpen: boolean
    mergeTargetId: string | null
    keepId: string | null
    mergeName: string
    mergeNameEdited: boolean
    merging: boolean
    candidates: MergeCandidate[]
    hiddenReleaseIds: Set<string>
    selectionDisabledReason: (releaseId: string) => string | null
}

interface ReleaseMergeLogicActions {
    loadReleases: () => void
    setSearch: (search: string) => { search: string }
    setStageFilter: (stage: ReleaseStage | null) => { stage: ReleaseStage | null }
    setDecisionOnly: (decisionOnly: boolean) => { decisionOnly: boolean }
    setSelection: (selection: RowSelectionState) => { selection: RowSelectionState }
    setMergeOpen: (open: boolean) => { open: boolean }
    openMergeInto: (releaseId: string) => { releaseId: string }
    setMergeTarget: (releaseId: string | null) => { releaseId: string | null }
    setMergeSources: (releaseIds: string[]) => { releaseIds: string[] }
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
        actions: [releaseLogic, ['loadReleases', 'setSearch', 'setStageFilter', 'setDecisionOnly']],
    })),
    actions({
        setSelection: (selection: RowSelectionState) => ({ selection }),
        setMergeOpen: (open: boolean) => ({ open }),
        openMergeInto: (releaseId: string) => ({ releaseId }),
        setMergeTarget: (releaseId: string | null) => ({ releaseId }),
        setMergeSources: (releaseIds: string[]) => ({ releaseIds }),
        setKeepId: (keepId: string) => ({ keepId }),
        setMergeName: (name: string) => ({ name }),
        editMergeName: (name: string) => ({ name }),
        mergeReleases: (keepId: string) => ({ keepId }),
        mergeReleasesDone: true,
    }),
    reducers({
        selection: [
            {} as RowSelectionState,
            {
                setSelection: (_, { selection }) => selection,
                setSearch: () => ({}),
                setStageFilter: () => ({}),
                setDecisionOnly: () => ({}),
            },
        ],
        mergeOpen: [false, { setMergeOpen: (_, { open }) => open }],
        mergeTargetId: [null as string | null, { setMergeTarget: (_, { releaseId }) => releaseId }],
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
        selectionDisabledReason: [
            (s) => [s.hiddenReleaseIds],
            (hiddenReleaseIds: Set<string>) =>
                (releaseId: string): string | null =>
                    hiddenReleaseIds.has(releaseId) ? 'This release links flags you can’t see' : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        openMergeInto: ({ releaseId }) => {
            actions.setMergeTarget(releaseId)
            actions.setSelection({ [releaseId]: true })
            actions.setMergeOpen(true)
        },
        setMergeSources: ({ releaseIds }) => {
            if (values.mergeTargetId) {
                actions.setSelection(
                    Object.fromEntries([values.mergeTargetId, ...releaseIds].map((releaseId) => [releaseId, true]))
                )
            }
        },
        setMergeOpen: ({ open }) => {
            if (!open && values.mergeTargetId) {
                actions.setSelection({})
                actions.setMergeTarget(null)
            }
            if (open) {
                const keepId = values.mergeTargetId ?? releaseToKeep(values.candidates)
                if (keepId) {
                    actions.setKeepId(keepId)
                }
                posthog.capture('release merge dialog opened', {
                    count: values.candidates.length,
                    from: values.mergeTargetId ? 'release page' : 'release list',
                })
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

import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visualReviewReposRetrieve, visualReviewReposSnapshotsList } from '../generated/api'
import type { RepoApi, SnapshotHistoryEntryApi } from '../generated/api.schemas'
import type { visualReviewSnapshotHistorySceneLogicType } from './visualReviewSnapshotHistorySceneLogicType'

export interface VisualReviewSnapshotHistorySceneLogicProps {
    repoId: string
    runType: string
    identifier: string
}

// Snapshots are stored per (identifier, run). Light/dark themes are stored as sibling
// identifiers (e.g. `foo--light` and `foo--dark`) sharing the same Run. We surface both
// in one timeline by fetching both identifiers and pairing entries by run_id.
export interface ThemePair {
    runId: string
    primary: SnapshotHistoryEntryApi
    partner: SnapshotHistoryEntryApi | null
    primaryTheme: 'light' | 'dark' | null
    partnerTheme: 'light' | 'dark' | null
}

function detectTheme(identifier: string): { stem: string; theme: 'light' | 'dark' | null } {
    if (identifier.endsWith('--light')) {
        return { stem: identifier.slice(0, -'--light'.length), theme: 'light' }
    }
    if (identifier.endsWith('--dark')) {
        return { stem: identifier.slice(0, -'--dark'.length), theme: 'dark' }
    }
    return { stem: identifier, theme: null }
}

export const visualReviewSnapshotHistorySceneLogic = kea<visualReviewSnapshotHistorySceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSnapshotHistorySceneLogic']),
    props({} as VisualReviewSnapshotHistorySceneLogicProps),
    key(({ repoId, runType, identifier }) => `${repoId}::${runType}::${identifier}`),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    loaders(({ props, values }) => ({
        repo: [
            null as RepoApi | null,
            {
                loadRepo: async () => {
                    return visualReviewReposRetrieve(String(values.currentProjectId), props.repoId)
                },
            },
        ],
        history: [
            [] as SnapshotHistoryEntryApi[],
            {
                loadHistory: async () => {
                    const response = await visualReviewReposSnapshotsList(
                        String(values.currentProjectId),
                        props.repoId,
                        props.runType,
                        encodeURIComponent(props.identifier),
                        { limit: 100 }
                    )
                    return response.results
                },
            },
        ],
        partnerHistory: [
            [] as SnapshotHistoryEntryApi[],
            {
                loadPartnerHistory: async () => {
                    const { stem, theme } = detectTheme(props.identifier)
                    if (!theme) {
                        return []
                    }
                    const partner = `${stem}--${theme === 'light' ? 'dark' : 'light'}`
                    const response = await visualReviewReposSnapshotsList(
                        String(values.currentProjectId),
                        props.repoId,
                        props.runType,
                        encodeURIComponent(partner),
                        { limit: 100 }
                    )
                    return response.results
                },
            },
        ],
    })),
    selectors({
        identifier: [() => [(_, p) => p.identifier], (identifier: string): string => identifier],
        runType: [() => [(_, p) => p.runType], (runType: string): string => runType],
        repoId: [() => [(_, p) => p.repoId], (repoId: string): string => repoId],
        primaryTheme: [
            () => [(_, p) => p.identifier],
            (identifier: string): 'light' | 'dark' | null => detectTheme(identifier).theme,
        ],
        // Pair entries by run_id so a single timeline row shows both themes.
        pairedHistory: [
            (s) => [s.history, s.partnerHistory, s.primaryTheme],
            (
                history: SnapshotHistoryEntryApi[],
                partnerHistory: SnapshotHistoryEntryApi[],
                primaryTheme: 'light' | 'dark' | null
            ): ThemePair[] => {
                const byRun = new Map<string, SnapshotHistoryEntryApi>()
                for (const e of partnerHistory) {
                    byRun.set(e.run_id, e)
                }
                const partnerTheme: 'light' | 'dark' | null =
                    primaryTheme === 'light' ? 'dark' : primaryTheme === 'dark' ? 'light' : null
                return history.map((e) => ({
                    runId: e.run_id,
                    primary: e,
                    partner: byRun.get(e.run_id) ?? null,
                    primaryTheme,
                    partnerTheme,
                }))
            },
        ],
        breadcrumbs: [
            () => [(_, p) => p.identifier, (_, p) => p.repoId],
            (identifier: string, repoId: string): Breadcrumb[] => [
                { key: 'visual_review', name: 'Visual review', path: '/visual_review' },
                {
                    key: ['visual_review_snapshots', repoId],
                    name: 'Snapshots',
                    path: urls.visualReviewSnapshotOverview(repoId),
                },
                { key: ['visual_review_snapshot_history', identifier], name: identifier },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRepo()
        actions.loadHistory()
        actions.loadPartnerHistory()
    }),
])

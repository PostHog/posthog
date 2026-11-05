import { MakeLogicType, actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { dashboardsBulkDeleteCreate, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import { insightsPartialUpdate, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import type { WizardRunArtifactApi } from '../../generated/api.schemas'

export type WizardRunNotebookArtifact = Extract<WizardRunArtifactApi, { artifact_type: 'notebook' }>

export type WizardSpendAuditCreatedKind = 'dashboard' | 'insight'

export interface WizardSpendAuditCreatedObject {
    kind: WizardSpendAuditCreatedKind
    id: number
    name: string
    url: string
    deleted: boolean
}

export interface WizardSpendAuditResultsLogicProps {
    projectId: string
    runId: string
    notebook: WizardRunNotebookArtifact
}

export interface wizardSpendAuditResultsLogicValues {
    notebookTitle: string | null
    notebookTitleLoading: boolean
    createdObjects: WizardSpendAuditCreatedObject[] | null
    createdObjectsLoading: boolean
    deletingKey: string | null
}

export interface wizardSpendAuditResultsLogicActions {
    loadNotebookTitle: () => { value: true }
    loadNotebookTitleSuccess: (notebookTitle: string | null) => { notebookTitle: string | null }
    loadNotebookTitleFailure: (error: string) => { error: string }
    loadCreatedObjects: () => { value: true }
    loadCreatedObjectsSuccess: (createdObjects: WizardSpendAuditCreatedObject[] | null) => {
        createdObjects: WizardSpendAuditCreatedObject[] | null
    }
    loadCreatedObjectsFailure: (error: string) => { error: string }
    deleteObject: (object: WizardSpendAuditCreatedObject) => { object: WizardSpendAuditCreatedObject }
    deleteObjectDone: (
        object: WizardSpendAuditCreatedObject,
        deleted: boolean
    ) => {
        object: WizardSpendAuditCreatedObject
        deleted: boolean
    }
}

export type wizardSpendAuditResultsLogicType = MakeLogicType<
    wizardSpendAuditResultsLogicValues,
    wizardSpendAuditResultsLogicActions,
    WizardSpendAuditResultsLogicProps
>

export function createdObjectKey(object: Pick<WizardSpendAuditCreatedObject, 'kind' | 'id'>): string {
    return `${object.kind}:${object.id}`
}

// Loads one name per object the run created. An object the user already deleted, or cannot see, still
// shows up so the list stays a complete record of what the run made.
async function loadCreatedObject(
    projectId: string,
    kind: WizardSpendAuditCreatedKind,
    id: number
): Promise<WizardSpendAuditCreatedObject> {
    try {
        if (kind === 'dashboard') {
            const dashboard = await dashboardsRetrieve(projectId, id)
            return { kind, id, name: dashboard.name || 'Untitled dashboard', url: urls.dashboard(id), deleted: false }
        }
        const insight = await insightsRetrieve(projectId, id)
        return {
            kind,
            id,
            name: insight.name || insight.derived_name || 'Untitled insight',
            url: urls.insightView(insight.short_id as InsightShortId),
            deleted: !!insight.deleted,
        }
    } catch {
        return {
            kind,
            id,
            name: kind === 'dashboard' ? `Dashboard ${id}` : `Insight ${id}`,
            url: '',
            deleted: true,
        }
    }
}

export const wizardSpendAuditResultsLogic = kea<wizardSpendAuditResultsLogicType>([
    path((runId) => ['products', 'wizard', 'wizardSpendAuditResultsLogic', runId]),
    props({} as WizardSpendAuditResultsLogicProps),
    key((props) => props.runId),
    actions({
        deleteObject: (object: WizardSpendAuditCreatedObject) => ({ object }),
        deleteObjectDone: (object: WizardSpendAuditCreatedObject, deleted: boolean) => ({ object, deleted }),
    }),
    loaders(({ props }) => ({
        notebookTitle: [
            null as string | null,
            {
                loadNotebookTitle: async () => {
                    const notebook = await notebooksRetrieve(props.projectId, props.notebook.short_id)
                    return notebook.title || 'Spend audit notebook'
                },
            },
        ],
        createdObjects: [
            null as WizardSpendAuditCreatedObject[] | null,
            {
                loadCreatedObjects: async () =>
                    await Promise.all([
                        ...props.notebook.dashboard_ids.map((id) =>
                            loadCreatedObject(props.projectId, 'dashboard', id)
                        ),
                        ...props.notebook.insight_ids.map((id) => loadCreatedObject(props.projectId, 'insight', id)),
                    ]),
            },
        ],
    })),
    reducers({
        deletingKey: [
            null as string | null,
            {
                deleteObject: (_, { object }) => createdObjectKey(object),
                deleteObjectDone: () => null,
            },
        ],
        createdObjects: {
            deleteObjectDone: (state, { object, deleted }) =>
                deleted && state
                    ? state.map((candidate) =>
                          createdObjectKey(candidate) === createdObjectKey(object)
                              ? { ...candidate, deleted: true }
                              : candidate
                      )
                    : state,
        },
    }),
    listeners(({ actions, props }) => ({
        deleteObject: async ({ object }) => {
            try {
                if (object.kind === 'dashboard') {
                    // The dashboard API forbids a hard delete and its PATCH schema has no `deleted`, so soft-delete
                    // through the bulk endpoint. Its insights stay, because the run lists them separately.
                    const result = await dashboardsBulkDeleteCreate(props.projectId, { ids: [object.id] })
                    if (!result.deleted.includes(object.id)) {
                        throw new Error('Dashboard was not deleted')
                    }
                } else {
                    await insightsPartialUpdate(props.projectId, object.id, { deleted: true })
                }
                // pinned: analytics event name, renaming it breaks dashboards
                posthog.capture('spend audit object deleted', {
                    wizard_run_id: props.runId,
                    object_kind: object.kind,
                })
                actions.deleteObjectDone(object, true)
            } catch {
                lemonToast.error(`Couldn't delete "${object.name}". Try again, or delete it from its own page.`)
                actions.deleteObjectDone(object, false)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadNotebookTitle()
            actions.loadCreatedObjects()
        },
    })),
])

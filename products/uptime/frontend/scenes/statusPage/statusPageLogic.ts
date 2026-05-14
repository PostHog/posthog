import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { MonitorSummary, uptimeSceneLogic } from '../uptimeSceneLogic'
import type { statusPageLogicType } from './statusPageLogicType'

export interface StatusPage {
    id: string
    title: string
    slug: string
    monitor_ids: string[]
    is_published: boolean
    published_at: string | null
    created_at: string
    updated_at: string
}

export interface StatusPageLogicProps {
    id: string
}

export const statusPageLogic = kea<statusPageLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'statusPage', 'statusPageLogic']),
    props({} as StatusPageLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [teamLogic, ['currentProjectId'], uptimeSceneLogic, ['monitorSummaries', 'monitorSummariesLoading']],
        actions: [uptimeSceneLogic, ['loadMonitorSummaries']],
    })),

    actions({
        setDraftTitle: (title: string) => ({ title }),
        setDraftSlug: (slug: string) => ({ slug }),
        clearDraftTitle: true,
        clearDraftSlug: true,
        commitTitle: true,
        commitSlug: true,
        toggleMonitor: (monitorId: string) => ({ monitorId }),
        reorderMonitors: (orderedIds: string[]) => ({ orderedIds }),
        publish: true,
        unpublish: true,
        setUrlPopoverOpen: (open: boolean) => ({ open }),
    }),

    reducers({
        draftTitle: [
            null as string | null,
            {
                setDraftTitle: (_, { title }) => title,
                clearDraftTitle: () => null,
                // Clear after the PATCH actually persists so the listener can still read the draft.
                patchStatusPageSuccess: () => null,
                loadStatusPageSuccess: () => null,
            },
        ],
        draftSlug: [
            null as string | null,
            {
                setDraftSlug: (_, { slug }) => slug,
                clearDraftSlug: () => null,
                patchStatusPageSuccess: () => null,
                loadStatusPageSuccess: () => null,
            },
        ],
        urlPopoverOpen: [
            false,
            {
                setUrlPopoverOpen: (_, { open }) => open,
            },
        ],
    }),

    loaders(({ props }) => ({
        statusPage: [
            null as StatusPage | null,
            {
                loadStatusPage: async () => {
                    return await api.get<StatusPage>(
                        `api/projects/${teamLogic.values.currentProjectId}/uptime/status_pages/${props.id}/`
                    )
                },
                patchStatusPage: async (payload: Partial<Pick<StatusPage, 'title' | 'slug' | 'monitor_ids'>>) => {
                    return await api.update<StatusPage>(
                        `api/projects/${teamLogic.values.currentProjectId}/uptime/status_pages/${props.id}/`,
                        payload
                    )
                },
                publishStatusPage: async () => {
                    return await api.create<StatusPage>(
                        `api/projects/${teamLogic.values.currentProjectId}/uptime/status_pages/${props.id}/publish/`,
                        {}
                    )
                },
                unpublishStatusPage: async () => {
                    return await api.create<StatusPage>(
                        `api/projects/${teamLogic.values.currentProjectId}/uptime/status_pages/${props.id}/unpublish/`,
                        {}
                    )
                },
            },
        ],
    })),

    selectors({
        displayTitle: [
            (s) => [s.draftTitle, s.statusPage],
            (draftTitle, page) => (draftTitle !== null ? draftTitle : (page?.title ?? '')),
        ],
        displaySlug: [
            (s) => [s.draftSlug, s.statusPage],
            (draftSlug, page) => (draftSlug !== null ? draftSlug : (page?.slug ?? '')),
        ],
        selectedMonitors: [
            (s) => [s.statusPage, s.monitorSummaries],
            (page, summaries: MonitorSummary[]): MonitorSummary[] => {
                if (!page) {
                    return []
                }
                const byId = new Map(summaries.map((m) => [m.id, m]))
                return page.monitor_ids.map((id) => byId.get(id)).filter((m): m is MonitorSummary => !!m)
            },
        ],
        availableMonitors: [
            (s) => [s.statusPage, s.monitorSummaries],
            (page, summaries: MonitorSummary[]): MonitorSummary[] => {
                if (!page) {
                    return summaries
                }
                const selected = new Set(page.monitor_ids)
                return summaries.filter((m) => !selected.has(m.id))
            },
        ],
        publicUrl: [
            (s) => [s.statusPage],
            (page): string | null => {
                if (!page) {
                    return null
                }
                if (typeof window === 'undefined') {
                    return `/status/${page.slug}`
                }
                return `${window.location.origin}/status/${page.slug}`
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        commitTitle: () => {
            const title = values.draftTitle?.trim()
            if (!title || title === values.statusPage?.title) {
                return
            }
            actions.patchStatusPage({ title })
        },
        commitSlug: () => {
            const slug = values.draftSlug?.trim()
            if (!slug || slug === values.statusPage?.slug) {
                return
            }
            actions.patchStatusPage({ slug })
        },
        toggleMonitor: ({ monitorId }) => {
            if (!values.statusPage) {
                return
            }
            const current = values.statusPage.monitor_ids
            const next = current.includes(monitorId)
                ? current.filter((id) => id !== monitorId)
                : [...current, monitorId]
            actions.patchStatusPage({ monitor_ids: next })
        },
        reorderMonitors: ({ orderedIds }) => {
            actions.patchStatusPage({ monitor_ids: orderedIds })
        },
        publish: () => {
            actions.publishStatusPage()
        },
        unpublish: () => {
            actions.unpublishStatusPage()
        },
        publishStatusPageSuccess: () => {
            lemonToast.success('Status page published')
            actions.setUrlPopoverOpen(true)
        },
        unpublishStatusPageSuccess: () => {
            lemonToast.info('Status page reverted to draft')
        },
        patchStatusPageFailure: ({ errorObject }) => {
            const slugError = errorObject?.data?.slug
            if (slugError) {
                lemonToast.error(typeof slugError === 'string' ? slugError : 'Slug already taken')
                actions.clearDraftSlug()
            }
        },
        loadStatusPageFailure: () => {
            router.actions.push('/uptime')
            lemonToast.error('Status page not found')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStatusPage()
        actions.loadMonitorSummaries()
    }),
])

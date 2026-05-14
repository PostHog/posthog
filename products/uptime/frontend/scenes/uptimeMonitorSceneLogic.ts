import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { openResolveIncidentDialog } from './incidentActions'
import type { uptimeMonitorSceneLogicType } from './uptimeMonitorSceneLogicType'
import { Incident, Monitor, MonitorSummary, Ping } from './uptimeSceneLogic'

export const uptimeMonitorSceneLogic = kea<uptimeMonitorSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeMonitorSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setMonitorId: (id: string | null) => ({ id }),
        pingNow: true,
        setEditModalOpen: (open: boolean) => ({ open }),
        deleteMonitor: true,
        openCreateIncident: true,
        startEditingIncident: (incident: Incident) => ({ incident }),
        closeIncidentModal: true,
        promptResolveIncident: (incident: Incident) => ({ incident }),
        reopenIncident: (incidentId: string) => ({ incidentId }),
        confirmDeleteIncident: (incident: { id: string; name: string }) => ({ incident }),
        deleteIncident: (incidentId: string) => ({ incidentId }),
    }),

    reducers({
        monitorId: [
            null as string | null,
            {
                setMonitorId: (_, { id }) => id,
            },
        ],
        editModalOpen: [
            false,
            {
                setEditModalOpen: (_, { open }) => open,
            },
        ],
        // null = closed; 'new' = create modal open; an id = edit modal open
        incidentModalState: [
            null as null | 'new' | string,
            {
                openCreateIncident: () => 'new',
                startEditingIncident: (_, { incident }) => incident.id,
                closeIncidentModal: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        summary: [
            null as MonitorSummary | null,
            {
                loadSummary: async () => {
                    if (!values.monitorId) {
                        return null
                    }
                    try {
                        return await api.get<MonitorSummary>(
                            `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/`
                        )
                    } catch (err: any) {
                        // 404 from retrieve = monitor genuinely gone (deleted, wrong id). Render the
                        // not-found state rather than letting the loader explode.
                        if (err?.status === 404) {
                            return null
                        }
                        throw err
                    }
                },
            },
        ],
        pings: [
            [] as Ping[],
            {
                loadPings: async () => {
                    if (!values.monitorId) {
                        return []
                    }
                    return await api.get<Ping[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/pings/`
                    )
                },
            },
        ],
        incidents: [
            [] as Incident[],
            {
                loadIncidents: async () => {
                    if (!values.monitorId) {
                        return []
                    }
                    return await api.get<Incident[]>(
                        `api/projects/${values.currentProjectId}/uptime/incidents/?monitor_id=${values.monitorId}`
                    )
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        editMonitor: {
            defaults: { name: '', url: '' } as { name: string; url: string },
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : null,
                url: !url ? 'URL is required' : null,
            }),
            submit: async ({ name, url }) => {
                if (!values.monitorId) {
                    return
                }
                const updated = await api.update<Monitor>(
                    `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/`,
                    { name, url }
                )
                lemonToast.success(`Monitor "${updated.name}" updated`)
                actions.setEditModalOpen(false)
                actions.loadSummary()
            },
        },
        incidentForm: {
            defaults: { name: '', description: '', resolution_note: '' } as {
                name: string
                description: string
                resolution_note: string
            },
            errors: ({ name, resolution_note }) => ({
                name: !name ? 'Name is required' : null,
                // Required only when editing a resolved incident — the field isn't shown otherwise.
                resolution_note:
                    values.editingIncident?.resolved_at && !resolution_note?.trim()
                        ? 'A resolution note is required'
                        : null,
            }),
            submit: async ({ name, description, resolution_note }) => {
                if (!values.monitorId) {
                    return
                }
                const state = values.incidentModalState
                if (state === 'new') {
                    await api.create<Incident>(`api/projects/${values.currentProjectId}/uptime/incidents/`, {
                        monitor_id: values.monitorId,
                        name,
                        description,
                    })
                    lemonToast.success('Declared incident')
                } else if (state) {
                    const payload: Record<string, string> = { name, description }
                    if (values.editingIncident?.resolved_at) {
                        payload.resolution_note = resolution_note
                    }
                    await api.update<Incident>(
                        `api/projects/${values.currentProjectId}/uptime/incidents/${state}/`,
                        payload
                    )
                    lemonToast.success('Declared incident updated')
                }
                actions.closeIncidentModal()
                actions.loadIncidents()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setMonitorId: () => {
            if (values.monitorId) {
                actions.loadSummary()
                actions.loadPings()
                actions.loadIncidents()
            }
        },
        loadSummarySuccess: ({ summary }) => {
            if (summary) {
                actions.setEditMonitorValues({ name: summary.name, url: summary.url })
            }
        },
        pingNow: async () => {
            if (!values.monitorId) {
                return
            }
            await api.create(
                `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/ping_now/`,
                {}
            )
            lemonToast.info('Ping enqueued — refresh in a few seconds')
        },
        deleteMonitor: async () => {
            if (!values.monitorId) {
                return
            }
            await api.delete(`api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/`)
            lemonToast.success('Monitor deleted')
            router.actions.push(urls.uptime())
        },
        openCreateIncident: () => {
            actions.setIncidentFormValues({ name: '', description: '' })
        },
        startEditingIncident: ({ incident }) => {
            actions.setIncidentFormValues({
                name: incident.name,
                description: incident.description,
                resolution_note: incident.resolution_note,
            })
        },
        promptResolveIncident: ({ incident }) => {
            openResolveIncidentDialog({
                incident,
                projectId: values.currentProjectId as string,
                onResolved: () => actions.loadIncidents(),
            })
        },
        reopenIncident: async ({ incidentId }) => {
            await api.create(`api/projects/${values.currentProjectId}/uptime/incidents/${incidentId}/reopen/`, {})
            lemonToast.info('Declared incident reopened')
            actions.loadIncidents()
        },
        confirmDeleteIncident: ({ incident }) => {
            LemonDialog.open({
                title: `Delete declared incident "${incident.name}"?`,
                description: 'This permanently removes the incident.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => actions.deleteIncident(incident.id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        deleteIncident: async ({ incidentId }) => {
            await api.delete(`api/projects/${values.currentProjectId}/uptime/incidents/${incidentId}/`)
            lemonToast.success('Declared incident deleted')
            actions.loadIncidents()
        },
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.summary, s.monitorId],
            (summary: MonitorSummary | null, monitorId: string | null): Breadcrumb[] => [
                { key: 'Uptime', name: 'Uptime', path: urls.uptime() },
                {
                    key: monitorId ?? 'monitor',
                    name: summary?.name ?? 'Monitor',
                },
            ],
        ],
        editingIncident: [
            (s) => [s.incidents, s.incidentModalState],
            (incidents: Incident[], state: null | 'new' | string): Incident | null => {
                if (!state || state === 'new') {
                    return null
                }
                return incidents.find((i) => i.id === state) ?? null
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        '/uptime/:id': (params) => {
            const id = params.id
            if (id && id !== values.monitorId) {
                actions.setMonitorId(id)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.monitorId) {
            actions.loadSummary()
            actions.loadPings()
            actions.loadIncidents()
        }
    }),
])

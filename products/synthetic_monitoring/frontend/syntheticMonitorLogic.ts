import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import type { syntheticMonitorLogicType } from './syntheticMonitorLogicType'
import { SyntheticMonitoringRegion } from './types'
import { SyntheticMonitor } from './types'

export interface SyntheticMonitorLogicProps {
    id?: string
}

export const syntheticMonitorLogic = kea<syntheticMonitorLogicType>([
    path(['products', 'synthetic_monitoring', 'frontend', 'syntheticMonitorLogic']),
    props({} as SyntheticMonitorLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setMonitor: (monitor: SyntheticMonitor | null) => ({ monitor }),
    }),
    loaders(({ props }) => ({
        monitor: [
            null as SyntheticMonitor | null,
            {
                loadMonitor: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return await api.syntheticMonitoring.get(props.id)
                },
            },
        ],
    })),
    forms(({ props, actions }) => ({
        monitorForm: {
            defaults: {
                name: '',
                url: '',
                frequency_minutes: 5 as const,
                regions: [SyntheticMonitoringRegion.US_EAST_1],
                method: 'GET',
                headers: null,
                body: null,
                expected_status_code: 200,
                timeout_seconds: 30,
            } as Partial<SyntheticMonitor>,
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : undefined,
                url: !url
                    ? 'URL is required'
                    : !url.startsWith('http://') && !url.startsWith('https://')
                      ? 'URL must start with http:// or https://'
                      : undefined,
            }),
            submit: async (monitor) => {
                try {
                    if (props.id && props.id !== 'new') {
                        const updated = await api.syntheticMonitoring.update(props.id, monitor)
                        lemonToast.success('Monitor updated successfully')
                        actions.setMonitor(updated)
                        router.actions.push(urls.syntheticMonitor(updated.id))
                    } else {
                        const created = await api.syntheticMonitoring.create(monitor)
                        lemonToast.success('Monitor created successfully')
                        router.actions.push(urls.syntheticMonitor(created.id))
                    }
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to save monitor')
                    throw error
                }
            },
        },
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.monitor],
            (monitor) => [
                { name: 'Synthetic monitoring', path: urls.syntheticMonitoring() },
                { name: monitor?.name || 'New monitor' },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        loadMonitorSuccess: ({ monitor }) => {
            if (monitor) {
                actions.setMonitorFormValues(monitor)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadMonitor()
        }
    }),
])

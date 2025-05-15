import { actions, afterMount, kea, listeners, path, props, reducers, selectors, sharedListeners } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { Breadcrumb, ProjectTreeRef } from '~/types'

import type { managedMigrationLogicType } from './managedMigrationLogicType'
import { ManagedMigration } from './types'

export interface ManagedMigrationForm {
    source: 'amplitude'
    api_key: string
    secret_key: string
    start_date: string
    end_date: string
    event_names: string[]
    event_names_mode: 'all' | 'allow' | 'deny'
}

const NEW_MANAGED_MIGRATION: ManagedMigrationForm = {
    source: 'amplitude',
    api_key: '',
    secret_key: '',
    start_date: dayjs().subtract(2, 'hour').startOf('hour').format('YYYY-MM-DD HH:mm:ss'),
    end_date: dayjs().subtract(1, 'hour').startOf('hour').format('YYYY-MM-DD HH:mm:ss'),
    event_names: [],
    event_names_mode: 'all',
}

export const managedMigrationLogic = kea<managedMigrationLogicType>([
    path(['products', 'managed_migrations', 'frontend', 'managedMigrationLogic']),
    props({
        managedMigrationId: '',
    }),
    actions({
        editManagedMigration: (id: string | null) => ({ id }),
    }),
    reducers({
        managedMigrationId: [null as string | null, { editManagedMigration: (_, { id }) => id }],
    }),
    loaders(() => ({
        migrations: [
            [] as ManagedMigration[],
            {
                loadMigrations: async () => {
                    const projectId = ApiConfig.getCurrentProjectId()
                    const response = await api.get(`api/projects/${projectId}/managed_migrations`)
                    return response.results
                },
            },
        ],
    })),
    forms({
        managedMigration: {
            defaults: NEW_MANAGED_MIGRATION as ManagedMigration,
            errors: ({ source, api_key, secret_key, start_date, end_date }) => ({
                source: !source ? 'Source is required' : null,
                api_key: !api_key ? 'API key is required' : null,
                secret_key: !secret_key ? 'Secret key is required' : null,
                start_date: !start_date ? 'Start date is required' : null,
                end_date: !end_date ? 'End date is required' : null,
            }),
            submit: async (values) => {
                const projectId = ApiConfig.getCurrentProjectId()
                const response = await api.create(`api/projects/${projectId}/managed_migrations`, values)
                router.actions.push(urls.managedMigration())
                return response
            },
        },
    }),
    sharedListeners(({ actions }: { actions: any }) => ({
        afterSubmit: async () => {
            await actions.loadMigrations()
        },
    })),
    listeners(({ actions, values, cache }) => ({
        loadMigrationsSuccess: () => {
            const hasRunningMigrations = values.migrations.some(
                (migration) => migration.status === 'Running' || migration.status === 'Starting'
            )
            if (hasRunningMigrations && !values.isPolling) {
                actions.startPolling()
            } else if (!hasRunningMigrations && values.isPolling) {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            const pollInterval = setInterval(() => {
                if (!values.isPolling) {
                    clearInterval(pollInterval)
                    return
                }
                actions.loadMigrations()
            }, 5000) // Poll every 5 seconds

            // Store the interval ID in the logic's cache
            cache.pollInterval = pollInterval
        },
        stopPolling: () => {
            if (cache.pollInterval) {
                clearInterval(cache.pollInterval)
                cache.pollInterval = null
            }
        },
    })),
    selectors({
        breadcrumbs: [
            (s, p) => [p.managedMigrationId],
            (managedMigrationId): Breadcrumb[] => [
                {
                    key: 'managed-migrations',
                    name: 'Managed Migrations',
                    path: urls.managedMigration(),
                },
                ...(managedMigrationId
                    ? [
                          {
                              key: 'edit-migration',
                              name: 'Manage migration',
                              path: urls.managedMigration(),
                          },
                      ]
                    : []),
            ],
        ],
        projectTreeRef: [
            (s, p) => [p.managedMigrationId],
            (managedMigrationId): ProjectTreeRef => ({
                type: 'managed-migration',
                ref: managedMigrationId,
            }),
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.managedMigrationNew()]: () => {
            actions.editManagedMigration('new')
        },
        [`${urls.managedMigration()}/:id`]: ({ id }) => {
            actions.editManagedMigration(id ?? null)
        },
        [urls.managedMigration()]: () => {
            actions.editManagedMigration(null)
        },
    })),
    afterMount(({ actions, values, cache }) => {
        actions.loadMigrations()

        // Start polling if there are running migrations
        const pollInterval = setInterval(() => {
            const hasRunningMigrations = values.migrations.some(
                (migration) => migration.status === 'Running' || migration.status === 'Starting'
            )

            if (hasRunningMigrations) {
                actions.loadMigrations()
            }
        }, 5000)

        // Store the interval ID in the logic's cache
        cache.pollInterval = pollInterval

        // Clean up on unmount
        return () => {
            if (cache.pollInterval) {
                clearInterval(cache.pollInterval)
            }
        }
    }),
])

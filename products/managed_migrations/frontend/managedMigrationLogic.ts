import {
    actions,
    afterMount,
    beforeUnmount,
    kea,
    listeners,
    path,
    props,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, ProjectTreeRef } from '~/types'

import type { managedMigrationLogicType } from './managedMigrationLogicType'
import { ManagedMigration } from './types'

export interface ManagedMigrationForm {
    source_type: 's3'
    access_key: string
    secret_key: string
    s3_region: string
    s3_bucket: string
    s3_prefix: string
    content_type: 'captured' | 'mixpanel' | 'amplitude'
}

const NEW_MANAGED_MIGRATION: ManagedMigrationForm = {
    source_type: 's3',
    access_key: '',
    secret_key: '',
    s3_region: '',
    s3_bucket: '',
    s3_prefix: '',
    content_type: 'captured',
}

export const managedMigrationLogic = kea<managedMigrationLogicType>([
    path(['products', 'managed_migrations', 'frontend', 'managedMigrationLogic']),
    props({
        managedMigrationId: null,
    }),
    actions({
        editManagedMigration: (id: string | null) => ({ id }),
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        managedMigrationId: [null as string | null, { editManagedMigration: (_, { id }) => id }],
        isPolling: [false, { startPolling: () => true, stopPolling: () => false }],
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
            errors: ({ source_type, access_key, secret_key, s3_region, s3_bucket }) => ({
                source_type: !source_type ? 'Source is required' : null,
                access_key: !access_key ? 'Access key is required' : null,
                secret_key: !secret_key ? 'Secret key is required' : null,
                s3_region: !s3_region ? 'S3 region is required' : null,
                s3_bucket: !s3_bucket ? 'S3 bucket is required' : null,
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
            const hasRunningMigrations = values.migrations.some((migration) => migration.status === 'running')
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
            }, 5000)

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
            (_, p) => [p.managedMigrationId],
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
            (_, p) => [p.managedMigrationId],
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
    afterMount(({ actions }) => {
        actions.loadMigrations()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])

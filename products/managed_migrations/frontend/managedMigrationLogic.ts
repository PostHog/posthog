import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { Breadcrumb, ProjectTreeRef } from '~/types'

import type { managedMigrationLogicType } from './managedMigrationLogicType'
import { ManagedMigration } from './types'

export interface ManagedMigrationForm {
    source_type: 's3' | 'mixpanel' | 'amplitude'
    access_key: string
    secret_key: string
    content_type: 'captured' | 'mixpanel' | 'amplitude'
    // s3 specific fields
    s3_region?: string
    s3_bucket?: string
    s3_prefix?: string
    // date range specific fields
    start_date?: string
    end_date?: string
}

const NEW_MANAGED_MIGRATION: ManagedMigrationForm = {
    source_type: 's3',
    access_key: '',
    secret_key: '',
    s3_region: '',
    s3_bucket: '',
    s3_prefix: '',
    content_type: 'captured',
    start_date: '',
    end_date: '',
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
            defaults: NEW_MANAGED_MIGRATION,
            errors: ({
                source_type,
                access_key,
                secret_key,
                s3_region,
                s3_bucket,
                start_date,
                end_date,
            }: ManagedMigrationForm) => {
                const errors: Record<string, string | null> = {
                    access_key: !access_key ? 'Access key is required' : null,
                    secret_key: !secret_key ? 'Secret key is required' : null,
                }

                if (source_type === 's3') {
                    errors.s3_region = !s3_region ? 'S3 region is required' : null
                    errors.s3_bucket = !s3_bucket ? 'S3 bucket is required' : null
                } else if (source_type === 'mixpanel' || source_type === 'amplitude') {
                    errors.start_date = !start_date ? 'Start date is required' : null
                    errors.end_date = !end_date ? 'End date is required' : null
                }
                return errors
            },
            submit: async (values: ManagedMigrationForm) => {
                const projectId = ApiConfig.getCurrentProjectId()
                let payload: ManagedMigrationForm = {
                    source_type: values.source_type,
                    access_key: values.access_key,
                    secret_key: values.secret_key,
                    content_type: values.content_type,
                }
                if (values.source_type === 's3') {
                    payload = {
                        ...payload,
                        s3_region: values.s3_region,
                        s3_bucket: values.s3_bucket,
                        s3_prefix: values.s3_prefix,
                    }
                } else if (values.source_type === 'mixpanel' || values.source_type === 'amplitude') {
                    payload = {
                        ...payload,
                        start_date: values.start_date,
                        end_date: values.end_date,
                    }
                }
                try {
                    const response = await api.create(`api/projects/${projectId}/managed_migrations`, payload)
                    return response
                } catch (error: any) {
                    if (error.status === 400 && error.data?.error) {
                        throw new Error(error.data.error)
                    }
                    throw error
                }
            },
        },
    }),
    listeners(({ actions, values, cache }) => ({
        submitManagedMigrationSuccess: async () => {
            actions.loadMigrations()
            router.actions.push(urls.managedMigration())
        },
        submitManagedMigrationFailure: async ({ error }) => {
            if (error?.message) {
                lemonToast.error(error.message)
            } else {
                lemonToast.error('Failed to create migration. Please try again.')
            }
        },
        loadMigrationsSuccess: () => {
            const hasRunningMigrations = values.migrations.some(
                (migration: ManagedMigration) => migration.status === 'running'
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
            (managedMigrationId: string | null): Breadcrumb[] => [
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
            (managedMigrationId: string | null): ProjectTreeRef => ({
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

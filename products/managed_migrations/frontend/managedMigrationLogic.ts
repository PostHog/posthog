import { actions, afterMount, kea, path, props, reducers, selectors } from 'kea'
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
    apiKey: string
    secretKey: string
    startDate: string
    endDate: string
    eventNames: string[]
    eventNamesMode: 'all' | 'allow' | 'deny'
}

const NEW_MANAGED_MIGRATION: ManagedMigrationForm = {
    source: 'amplitude',
    apiKey: '',
    secretKey: '',
    startDate: dayjs().subtract(2, 'year').startOf('hour').format('YYYY-MM-DD HH:mm:ss'),
    endDate: dayjs().subtract(1, 'hour').startOf('hour').format('YYYY-MM-DD HH:mm:ss'),
    eventNames: [],
    eventNamesMode: 'all',
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
            errors: ({ source, apiKey, secretKey, startDate, endDate }) => ({
                source: !source ? 'Source is required' : null,
                apiKey: !apiKey ? 'API key is required' : null,
                secretKey: !secretKey ? 'Secret key is required' : null,
                startDate: !startDate ? 'Start date is required' : null,
                endDate: !endDate ? 'End date is required' : null,
            }),
            submit: async (values) => {
                const projectId = ApiConfig.getCurrentProjectId()
                const response = await api.create(`api/projects/${projectId}/managed_migrations`, values)
                router.actions.push(urls.managedMigration())
                return response
            },
        },
    }),
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
    afterMount(({ actions }) => {
        actions.loadMigrations()
    }),
])

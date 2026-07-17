import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb, ProjectTreeRef } from '~/types'

import { managedMigrationsPromoteCreate, managedMigrationsTrialRecordsRetrieve } from './generated/api'
import type { TrialRecordsResponseApi } from './generated/api.schemas'
import type { managedMigrationLogicType } from './managedMigrationLogicType'
import { ManagedMigration } from './types'

export interface ManagedMigrationForm {
    source_type: 's3' | 's3_gzip' | 'mixpanel' | 'amplitude'
    access_key: string
    secret_key: string
    content_type: 'captured' | 'mixpanel' | 'amplitude'
    // s3 specific fields
    s3_region?: string
    s3_bucket?: string
    s3_prefix?: string
    endpoint_url?: string
    // date range specific fields
    start_date?: string
    end_date?: string
    // EU region support for amplitude/mixpanel
    is_eu_region?: boolean
    // Amplitude-specific options
    import_events?: boolean
    generate_identify_events?: boolean
    generate_group_identify_events?: boolean
    // Trial run options
    is_trial?: boolean
    trial_record_limit?: number
}

export const TRIAL_RECORD_LIMIT_DEFAULT = 1000
export const TRIAL_RECORD_LIMIT_MAX = 50000

const NEW_MANAGED_MIGRATION: ManagedMigrationForm = {
    source_type: 's3',
    access_key: '',
    secret_key: '',
    s3_region: '',
    s3_bucket: '',
    s3_prefix: '',
    endpoint_url: '',
    content_type: 'captured',
    start_date: '',
    end_date: '',
    is_eu_region: false,
    import_events: true,
    generate_identify_events: true,
    generate_group_identify_events: true,
    is_trial: false,
    trial_record_limit: TRIAL_RECORD_LIMIT_DEFAULT,
}

export const managedMigrationLogic = kea<managedMigrationLogicType>([
    path(['products', 'managed_migrations', 'frontend', 'managedMigrationLogic']),
    props({
        managedMigrationId: null,
    }),
    actions({
        editManagedMigration: (id: string | null) => ({ id }),
        pauseMigration: (id: string) => ({ id }),
        resumeMigration: (id: string) => ({ id }),
        promoteTrial: (id: string) => ({ id }),
        confirmPromoteTrial: (id: string) => ({ id }),
        promoteTrialFinished: true,
        viewTrialResults: (id: string) => ({ id }),
        closeTrialResults: true,
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        managedMigrationId: [null as string | null, { editManagedMigration: (_, { id }) => id }],
        isPolling: [false, { startPolling: () => true, stopPolling: () => false }],
        trialResultsId: [null as string | null, { viewTrialResults: (_, { id }) => id, closeTrialResults: () => null }],
        promotingMigrationId: [
            null as string | null,
            { confirmPromoteTrial: (_, { id }) => id, promoteTrialFinished: () => null },
        ],
    }),
    loaders(({ values }) => ({
        migrations: [
            [] as ManagedMigration[],
            {
                loadMigrations: async () => {
                    const projectId = ApiConfig.getCurrentProjectId()
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get(`api/projects/${projectId}/managed_migrations`)
                    return response.results
                },
            },
        ],
        trialRecords: [
            null as TrialRecordsResponseApi | null,
            {
                loadTrialRecordsPage: async ({ page }: { page: number }, breakpoint) => {
                    if (!values.trialResultsId) {
                        return null
                    }
                    await breakpoint(100)
                    const projectId = String(ApiConfig.getCurrentProjectId())
                    return await managedMigrationsTrialRecordsRetrieve(projectId, values.trialResultsId, { page })
                },
                closeTrialResults: () => null,
            },
        ],
    })),
    forms({
        managedMigration: {
            defaults: NEW_MANAGED_MIGRATION,
            errors: ({
                source_type,
                content_type,
                access_key,
                secret_key,
                s3_region,
                s3_bucket,
                start_date,
                end_date,
                import_events,
                generate_identify_events,
                generate_group_identify_events,
                is_trial,
                trial_record_limit,
            }: ManagedMigrationForm) => {
                const errors: Record<string, string | null> = {
                    secret_key: !secret_key
                        ? source_type === 'mixpanel'
                            ? 'Project secret is required'
                            : 'Secret key is required'
                        : null,
                }

                if (is_trial) {
                    errors.trial_record_limit =
                        !trial_record_limit || trial_record_limit < 1 || trial_record_limit > TRIAL_RECORD_LIMIT_MAX
                            ? `Number of records must be between 1 and ${TRIAL_RECORD_LIMIT_MAX}`
                            : null
                }

                // Mixpanel authenticates with the project secret alone — no access key.
                if (source_type !== 'mixpanel') {
                    errors.access_key = !access_key ? 'Access key is required' : null
                }

                if (source_type === 's3' || source_type === 's3_gzip') {
                    errors.s3_region = !s3_region ? 'S3 region is required' : null
                    errors.s3_bucket = !s3_bucket ? 'S3 bucket is required' : null

                    if (content_type === 'amplitude') {
                        if (!import_events && !generate_identify_events && !generate_group_identify_events) {
                            errors.import_events =
                                'At least one of "Import events", "Generate identify events", or "Generate group identify events" must be enabled'
                        }
                    }
                } else if (source_type === 'mixpanel' || source_type === 'amplitude') {
                    errors.start_date = !start_date ? 'Start date is required' : null
                    errors.end_date = !end_date ? 'End date is required' : null

                    if (start_date && end_date) {
                        const startDateParsed = dayjs(start_date)
                        const endDateParsed = dayjs(end_date)

                        if (endDateParsed.isBefore(startDateParsed)) {
                            errors.end_date = 'End date must be after start date'
                        } else if (endDateParsed.diff(startDateParsed, 'year', true) > 1) {
                            errors.end_date =
                                'Date range cannot exceed 1 year. Please create multiple migration jobs for longer periods.'
                        } else if (
                            source_type === 'amplitude' &&
                            endDateParsed.diff(startDateParsed, 'hour', true) < 1
                        ) {
                            errors.end_date = 'Date range must be at least 1 hour for Amplitude migrations.'
                        }
                    }

                    // For Amplitude, ensure at least one of import_events, generate_identify_events, or generate_group_identify_events is enabled
                    if (source_type === 'amplitude') {
                        if (!import_events && !generate_identify_events && !generate_group_identify_events) {
                            errors.import_events =
                                'At least one of "Import events", "Generate identify events", or "Generate group identify events" must be enabled'
                        }
                    }
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
                    ...(values.is_trial ? { is_trial: true, trial_record_limit: values.trial_record_limit } : {}),
                }
                if (values.source_type === 's3' || values.source_type === 's3_gzip') {
                    payload = {
                        ...payload,
                        s3_region: values.s3_region,
                        s3_bucket: values.s3_bucket,
                        s3_prefix: values.s3_prefix,
                        ...(values.endpoint_url ? { endpoint_url: values.endpoint_url } : {}),
                    }

                    if (values.content_type === 'amplitude') {
                        payload.import_events = values.import_events
                        payload.generate_identify_events = values.generate_identify_events
                        payload.generate_group_identify_events = values.generate_group_identify_events
                    }
                } else if (values.source_type === 'mixpanel' || values.source_type === 'amplitude') {
                    payload = {
                        ...payload,
                        start_date: values.start_date,
                        end_date: values.end_date,
                        is_eu_region: values.is_eu_region,
                    }

                    // Only include Amplitude-specific options for Amplitude migrations
                    if (values.source_type === 'amplitude') {
                        payload.import_events = values.import_events
                        payload.generate_identify_events = values.generate_identify_events
                        payload.generate_group_identify_events = values.generate_group_identify_events
                    }
                }
                try {
                    // nosemgrep: prefer-codegen-api
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
        submitManagedMigrationSuccess: async ({ managedMigration }) => {
            if (managedMigration?.is_trial) {
                lemonToast.success('Trial run started — results will appear here when it completes')
            }
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
        pauseMigration: async ({ id }) => {
            try {
                const projectId = ApiConfig.getCurrentProjectId()
                // nosemgrep: prefer-codegen-api
                await api.create(`api/projects/${projectId}/managed_migrations/${id}/pause/`)
                lemonToast.success('Migration paused successfully')
                actions.loadMigrations()
            } catch (error: any) {
                lemonToast.error(error?.message || 'Failed to pause migration')
            }
        },
        resumeMigration: async ({ id }) => {
            try {
                const projectId = ApiConfig.getCurrentProjectId()
                // nosemgrep: prefer-codegen-api
                await api.create(`api/projects/${projectId}/managed_migrations/${id}/resume/`)
                lemonToast.success('Migration resumed successfully')
                actions.loadMigrations()
            } catch (error: any) {
                lemonToast.error(error?.message || 'Failed to resume migration')
            }
        },
        viewTrialResults: () => {
            actions.loadTrialRecordsPage({ page: 0 })
        },
        loadTrialRecordsPageFailure: async ({ errorObject }) => {
            if (errorObject?.status === 410) {
                lemonToast.error('Trial results have expired and are no longer available')
            } else {
                lemonToast.error('Failed to load trial results')
            }
            actions.closeTrialResults()
        },
        promoteTrial: ({ id }) => {
            const trial = values.migrations.find((migration: ManagedMigration) => migration.id === id)
            const failedRecords = trial?.state?.trial?.summary?.dropped_records ?? 0
            if (failedRecords === 0) {
                actions.confirmPromoteTrial(id)
                return
            }
            LemonDialog.open({
                title: 'Start the full import?',
                description: `This trial found ${failedRecords} record${
                    failedRecords === 1 ? '' : 's'
                } that can't be imported. These errors are not retriable: the import will pause when it reaches the first failing record, and stay paused until the source data is fixed.`,
                primaryButton: {
                    children: 'Start import anyway',
                    type: 'primary',
                    onClick: () => actions.confirmPromoteTrial(id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        confirmPromoteTrial: async ({ id }) => {
            try {
                const projectId = String(ApiConfig.getCurrentProjectId())
                await managedMigrationsPromoteCreate(projectId, id)
                lemonToast.success('Import started from trial run')
                actions.loadMigrations()
            } catch (error: any) {
                lemonToast.error(error?.data?.error || error?.message || 'Failed to start import from trial')
            } finally {
                actions.promoteTrialFinished()
            }
        },
        loadMigrationsSuccess: () => {
            const hasActiveMigrations = values.migrations.some(
                (migration: ManagedMigration) =>
                    migration.display_status === 'running' || migration.display_status === 'waiting_to_start'
            )
            if (hasActiveMigrations && !values.isPolling) {
                actions.startPolling()
            } else if (!hasActiveMigrations && values.isPolling) {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const intervalId = setInterval(() => {
                    actions.loadMigrations()
                }, 5000)
                return () => clearInterval(intervalId)
            }, 'pollMigrations')
        },
        stopPolling: () => {
            cache.disposables.dispose('pollMigrations')
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
                    iconType: 'data_pipeline_metadata',
                },
                ...(managedMigrationId
                    ? [
                          {
                              key: 'edit-migration',
                              name: 'Manage migration',
                              path: urls.managedMigration(),
                              iconType: 'data_pipeline_metadata' as FileSystemIconType,
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

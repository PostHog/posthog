import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconSort } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { managedMigrationLogic } from './managedMigrationLogic'
import { type ManagedMigration } from './types'

const STATUS_COLORS = {
    running: 'primary',
    completed: 'success',
    paused: 'danger',
} as const

function StatusTag({ status }: { status: string }): JSX.Element {
    return (
        <LemonTag type={STATUS_COLORS[status as keyof typeof STATUS_COLORS] || 'default'}>
            {status.charAt(0).toUpperCase() + status.slice(1)}
        </LemonTag>
    )
}

export function ManagedMigration(): JSX.Element {
    const { managedMigration } = useValues(managedMigrationLogic)
    const { setManagedMigrationValue } = useActions(managedMigrationLogic)

    return (
        <Form logic={managedMigrationLogic} formKey="managedMigration" enableFormOnSubmit className="space-y-4">
            <SceneContent>
                <SceneTitleSection
                    name="New managed migration"
                    resourceType={{ type: 'managed_migration', forceIcon: <IconSort /> }}
                    actions={
                        <LemonButton type="primary" htmlType="submit" size="small">
                            Import Data
                        </LemonButton>
                    }
                    forceBackTo={{
                        path: urls.managedMigration(),
                        key: 'managed_migrations',
                        name: 'Managed migrations',
                    }}
                />
                <LemonField name="source_type" label="Source">
                    <LemonSelect
                        value={managedMigration.source_type}
                        onChange={(value) => {
                            setManagedMigrationValue('source_type', value)
                            if (value === 'mixpanel' || value === 'amplitude') {
                                setManagedMigrationValue('content_type', value)
                            }
                        }}
                        options={[
                            {
                                value: 's3',
                                label: 'S3',
                                icon: (
                                    <img
                                        src="https://a0.awsstatic.com/libra-css/images/site/fav/favicon.ico"
                                        className="w-4 h-4"
                                    />
                                ),
                            },
                            {
                                value: 'mixpanel',
                                label: 'Mixpanel',
                                icon: <img src="https://mixpanel.com/favicon.ico" className="w-4 h-4" />,
                            },
                            {
                                value: 'amplitude',
                                label: 'Amplitude',
                                icon: <img src="https://amplitude.com/favicon.ico" className="w-4 h-4" />,
                            },
                        ]}
                    />
                </LemonField>

                {managedMigration.source_type === 's3' && (
                    <>
                        <LemonField name="content_type" label="Content Type">
                            <LemonSelect
                                value={managedMigration.content_type}
                                onChange={(value) => setManagedMigrationValue('content_type', value)}
                                options={[
                                    { value: 'captured', label: 'PostHog Events' },
                                    { value: 'mixpanel', label: 'Mixpanel Events' },
                                    { value: 'amplitude', label: 'Amplitude Events' },
                                ]}
                            />
                        </LemonField>
                    </>
                )}

                {managedMigration.source_type === 's3' && (
                    <>
                        <div className="flex gap-4">
                            <LemonField name="s3_region" label="S3 Region" className="flex-1">
                                <LemonInput placeholder="us-east-1" />
                            </LemonField>

                            <LemonField name="s3_bucket" label="S3 Bucket" className="flex-1">
                                <LemonInput placeholder="my-bucket" />
                            </LemonField>
                        </div>

                        <LemonField name="s3_prefix" label="S3 Prefix (optional)">
                            <LemonInput placeholder="path/to/files/" />
                        </LemonField>
                    </>
                )}
                {(managedMigration.source_type === 'mixpanel' || managedMigration.source_type === 'amplitude') && (
                    <>
                        <div className="flex gap-4">
                            <LemonField name="start_date" label="Start Date" className="flex-1">
                                <LemonCalendarSelectInput
                                    granularity="minute"
                                    value={managedMigration.start_date ? dayjs(managedMigration.start_date) : null}
                                    onChange={(date) =>
                                        setManagedMigrationValue('start_date', date?.format('YYYY-MM-DD HH:mm:ss'))
                                    }
                                />
                            </LemonField>

                            <LemonField name="end_date" label="End Date" className="flex-1">
                                <LemonCalendarSelectInput
                                    granularity="minute"
                                    value={managedMigration.end_date ? dayjs(managedMigration.end_date) : null}
                                    onChange={(date) =>
                                        setManagedMigrationValue('end_date', date?.format('YYYY-MM-DD HH:mm:ss'))
                                    }
                                />
                            </LemonField>
                        </div>

                        <LemonField name="is_eu_region">
                            <LemonCheckbox
                                checked={managedMigration.is_eu_region || false}
                                onChange={(checked) => setManagedMigrationValue('is_eu_region', checked)}
                                label="Use EU region endpoint"
                            />
                        </LemonField>

                        {managedMigration.source_type === 'amplitude' && (
                            <FlaggedFeature flag={FEATURE_FLAGS.AMPLITUDE_BATCH_IMPORT_OPTIONS}>
                                <LemonField name="import_events">
                                    <LemonCheckbox
                                        checked={managedMigration.import_events !== false}
                                        onChange={(checked) => setManagedMigrationValue('import_events', checked)}
                                        label="Import events from Amplitude"
                                    />
                                </LemonField>

                                <LemonField name="generate_identify_events">
                                    <LemonCheckbox
                                        checked={managedMigration.generate_identify_events !== false}
                                        onChange={(checked) =>
                                            setManagedMigrationValue('generate_identify_events', checked)
                                        }
                                        label="Generate identify events to link user IDs with device IDs"
                                    />
                                </LemonField>

                                <LemonField name="generate_group_identify_events">
                                    <LemonCheckbox
                                        checked={managedMigration.generate_group_identify_events === true}
                                        onChange={(checked) =>
                                            setManagedMigrationValue('generate_group_identify_events', checked)
                                        }
                                        label="Generate group identify events from group property changes"
                                    />
                                </LemonField>
                            </FlaggedFeature>
                        )}
                    </>
                )}

                <div className="flex gap-4">
                    <LemonField name="access_key" label="Access Key ID" className="flex-1">
                        <LemonInput type="password" />
                    </LemonField>

                    <LemonField name="secret_key" label="Secret Access Key" className="flex-1">
                        <LemonInput type="password" />
                    </LemonField>
                </div>

                <div className="flex justify-end">
                    <LemonButton type="primary" htmlType="submit">
                        Import Data
                    </LemonButton>
                </div>
            </SceneContent>
        </Form>
    )
}

export function ManagedMigrations(): JSX.Element {
    const { managedMigrationId, migrations, migrationsLoading } = useValues(managedMigrationLogic)
    const { pauseMigration, resumeMigration } = useActions(managedMigrationLogic)

    const calculateProgress = (migration: ManagedMigration): { progress: number; completed: number; total: number } => {
        if (migration.state?.parts && Array.isArray(migration.state.parts)) {
            const parts = migration.state.parts
            const totalParts = parts.length
            const completedParts = parts.filter(
                (part) => part.total_size !== null && part.total_size === part.current_offset
            ).length
            return {
                progress: totalParts > 0 ? (completedParts / totalParts) * 100 : 0,
                completed: completedParts,
                total: totalParts,
            }
        }
        return { progress: 0, completed: 0, total: 0 }
    }

    return (
        <SceneContent>
            {managedMigrationId ? (
                <ManagedMigration />
            ) : (
                <>
                    <SceneTitleSection
                        name="Managed migrations"
                        resourceType={{
                            type: 'managed_migration',
                            forceIcon: <IconSort />,
                        }}
                        actions={
                            <LemonButton
                                data-attr="new-managed-migration"
                                to={urls.managedMigrationNew()}
                                type="primary"
                                size="small"
                            >
                                New migration
                            </LemonButton>
                        }
                    />
                    <LemonTable
                        dataSource={migrations}
                        loading={migrationsLoading}
                        defaultSorting={{
                            columnKey: 'created_at',
                            order: -1,
                        }}
                        columns={[
                            {
                                title: 'Source',
                                dataIndex: 'source_type',
                                render: (_: any, migration: ManagedMigration) => {
                                    let sourceType: string = migration.source_type
                                    if (migration.source_type === 'date_range_export') {
                                        sourceType = migration.content_type
                                    }
                                    const sourceTypeMap = {
                                        s3: {
                                            icon: 'https://a0.awsstatic.com/libra-css/images/site/fav/favicon.ico',
                                            label: 'AWS S3',
                                            alt: 'S3',
                                        },
                                        mixpanel: {
                                            icon: 'https://mixpanel.com/favicon.ico',
                                            label: 'Mixpanel',
                                            alt: 'Mixpanel',
                                        },
                                        amplitude: {
                                            icon: 'https://amplitude.com/favicon.ico',
                                            label: 'Amplitude',
                                            alt: 'Amplitude',
                                        },
                                    }

                                    const config = sourceTypeMap[sourceType as keyof typeof sourceTypeMap]

                                    if (!config) {
                                        return sourceType
                                    }

                                    return (
                                        <div className="flex items-center gap-2">
                                            <img src={config.icon} alt={config.alt} className="w-4 h-4" />
                                            {config.label}
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Content Type',
                                dataIndex: 'content_type',
                                render: (_: any, migration: ManagedMigration) => {
                                    const contentTypeConfig = {
                                        captured: {
                                            icon: '/static/icons/favicon.ico?v=2023-07-07',
                                            alt: 'PostHog',
                                        },
                                        mixpanel: {
                                            icon: 'https://mixpanel.com/favicon.ico',
                                            alt: 'Mixpanel',
                                        },
                                        amplitude: {
                                            icon: 'https://amplitude.com/favicon.ico',
                                            alt: 'Amplitude',
                                        },
                                    }

                                    const config =
                                        contentTypeConfig[migration.content_type as keyof typeof contentTypeConfig]

                                    if (!config) {
                                        return migration.content_type
                                    }

                                    return (
                                        <div className="flex items-center justify-center gap-2">
                                            <img src={config.icon} alt={config.alt} className="w-4 h-4" />
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Status',
                                dataIndex: 'status',
                                render: (_: any, migration: ManagedMigration) => (
                                    <StatusTag status={migration.status} />
                                ),
                            },
                            {
                                title: 'Progress',
                                key: 'progress',
                                render: (_: any, migration: ManagedMigration) => {
                                    const { progress, completed, total } = calculateProgress(migration)
                                    return (
                                        <div className="flex flex-col gap-1">
                                            <LemonProgress
                                                percent={progress}
                                                strokeColor={
                                                    migration.status === 'paused' ? 'var(--danger)' : undefined
                                                }
                                            />
                                            <span className="text-xs text-muted">
                                                {migration.status === 'completed'
                                                    ? 'Complete'
                                                    : migration.status === 'paused'
                                                      ? 'Paused'
                                                      : `${completed}/${total}`}
                                            </span>
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Created by',
                                dataIndex: 'created_by',
                                render: function Render(_: any, migration: ManagedMigration) {
                                    return (
                                        <div className="flex flex-row items-center flex-nowrap">
                                            {migration.created_by && (
                                                <ProfilePicture user={migration.created_by} size="md" showName />
                                            )}
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Created',
                                dataIndex: 'created_at',
                                render: function Render(dataValue: any) {
                                    if (typeof dataValue === 'string') {
                                        return (
                                            <div className="whitespace-nowrap text-right">
                                                <TZLabel time={dayjs(dataValue)} />
                                            </div>
                                        )
                                    }
                                    return <span className="text-secondary">—</span>
                                },
                                align: 'right',
                            },
                            {
                                title: 'Status Message',
                                dataIndex: 'status_message',
                                render: (_: any, migration: ManagedMigration) => migration.status_message || '-',
                            },
                            {
                                title: 'Actions',
                                key: 'actions',
                                render: (_: any, migration: ManagedMigration) => {
                                    if (migration.status === 'running') {
                                        return (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() => pauseMigration(migration.id)}
                                                loading={migrationsLoading}
                                            >
                                                Pause
                                            </LemonButton>
                                        )
                                    } else if (migration.status === 'paused') {
                                        return (
                                            <LemonButton
                                                type="primary"
                                                size="small"
                                                onClick={() => resumeMigration(migration.id)}
                                                loading={migrationsLoading}
                                            >
                                                Resume
                                            </LemonButton>
                                        )
                                    }
                                    return null
                                },
                            },
                        ]}
                        emptyState="No migrations found. Create a new migration to get started."
                    />
                </>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: ManagedMigrations,
    logic: managedMigrationLogic,
}

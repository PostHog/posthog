import { LemonButton } from '@posthog/lemon-ui'
import { LemonTable, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
            <LemonField name="source_type" label="Source">
                <LemonSelect
                    value={managedMigration.source_type}
                    onChange={(value) => setManagedMigrationValue('source_type', value)}
                    options={[
                        {
                            value: 's3',
                            label: 'S3',
                            icon: <img src="https://a0.awsstatic.com/libra-css/images/site/fav/favicon.ico" />,
                        },
                    ]}
                />
            </LemonField>

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
        </Form>
    )
}

export function ManagedMigrations(): JSX.Element {
    const { managedMigrationId, migrations, migrationsLoading } = useValues(managedMigrationLogic)

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

    return managedMigrationId ? (
        <ManagedMigration />
    ) : (
        <>
            <PageHeader
                caption="Import data from S3"
                buttons={
                    <LemonButton data-attr="new-managed-migration" to={urls.managedMigrationNew()} type="primary">
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
                        render: () => (
                            <div className="flex items-center gap-2">
                                <img
                                    src="https://a0.awsstatic.com/libra-css/images/site/fav/favicon.ico"
                                    alt="S3"
                                    className="w-4 h-4"
                                />
                                AWS S3
                            </div>
                        ),
                    },
                    {
                        title: 'Content Type',
                        dataIndex: 'content_type',
                        render: (_, migration) => {
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

                            const config = contentTypeConfig[migration.content_type as keyof typeof contentTypeConfig]

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
                        render: (_, migration) => <StatusTag status={migration.status} />,
                    },
                    {
                        title: 'Progress',
                        key: 'progress',
                        render: (_, migration) => {
                            const { progress, completed, total } = calculateProgress(migration)
                            return (
                                <div className="flex flex-col gap-1">
                                    <LemonProgress
                                        percent={progress}
                                        strokeColor={migration.status === 'paused' ? 'var(--danger)' : undefined}
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
                        render: function Render(_: any, migration) {
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
                        title: 'Error',
                        dataIndex: 'error',
                        render: (_, migration) => migration.error || '-',
                    },
                ]}
                emptyState="No migrations found. Create a new migration to get started."
            />
        </>
    )
}

export const scene: SceneExport = {
    component: ManagedMigrations,
    logic: managedMigrationLogic,
}

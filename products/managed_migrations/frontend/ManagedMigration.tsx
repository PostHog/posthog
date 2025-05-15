import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { LemonTable, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import api, { ApiConfig } from 'lib/api'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { managedMigrationLogic } from './managedMigrationLogic'

interface Migration {
    id: string
    source: string
    status: 'Cancelled' | 'Completed' | 'Failed' | 'Running' | 'Starting'
    start_date: string
    end_date: string
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    }
    created_at: string
    error: string | null
    event_names_mode: 'all' | 'allow' | 'deny'
    event_names: string[] | null
}

const STATUS_COLORS = {
    starting: 'warning',
    running: 'primary',
    completed: 'success',
    failed: 'danger',
    cancelled: 'default',
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
            <LemonField name="source" label="Source">
                <LemonSelect
                    options={[
                        {
                            value: 'amplitude',
                            label: (
                                <div className="flex items-center gap-2">
                                    <img src="https://amplitude.com/favicon.ico" alt="Amplitude" className="w-4 h-4" />
                                    Amplitude
                                </div>
                            ),
                        },
                        {
                            value: 'mixpanel',
                            label: (
                                <div className="flex items-center gap-2">
                                    <img src="https://mixpanel.com/favicon.ico" alt="Mixpanel" className="w-4 h-4" />
                                    Mixpanel
                                </div>
                            ),
                        },
                    ]}
                />
            </LemonField>

            <LemonField name="api_key" label="API Key">
                <LemonInput type="password" />
            </LemonField>

            <LemonField name="secret_key" label="Secret Key">
                <LemonInput type="password" />
            </LemonField>

            <div className="flex gap-4">
                <LemonField name="start_date" label="Start Date" className="flex-1">
                    <LemonCalendarSelectInput
                        granularity="minute"
                        value={managedMigration.start_date ? dayjs(managedMigration.start_date) : null}
                        onChange={(date) =>
                            setManagedMigrationValue('start_date', date?.format('YYYY-MM-DD HH:mm:ss') || '')
                        }
                    />
                </LemonField>

                <LemonField name="end_date" label="End Date" className="flex-1">
                    <LemonCalendarSelectInput
                        granularity="minute"
                        value={managedMigration.end_date ? dayjs(managedMigration.end_date) : null}
                        onChange={(date) =>
                            setManagedMigrationValue('end_date', date?.format('YYYY-MM-DD HH:mm:ss') || '')
                        }
                    />
                </LemonField>
            </div>

            <div className="flex flex-col gap-2">
                <LemonField name="event_names_mode" label="Events">
                    <LemonSelect
                        options={[
                            { value: 'all', label: 'Import all events' },
                            { value: 'allow', label: 'Only import these events' },
                            { value: 'deny', label: "Don't import these events" },
                        ]}
                    />
                </LemonField>

                {managedMigration.event_names_mode !== 'all' && (
                    <LemonField name="event_names">
                        <LemonInputSelect
                            mode="multiple"
                            placeholder="Enter event names"
                            value={managedMigration.event_names}
                            onChange={(value) => setManagedMigrationValue('event_names', value)}
                            allowCustomValues
                        />
                    </LemonField>
                )}
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
    const { loadMigrations } = useActions(managedMigrationLogic)

    const handleCancel = async (migrationId: string): Promise<void> => {
        try {
            const projectId = ApiConfig.getCurrentProjectId()
            await api.create(`api/projects/${projectId}/managed_migrations/${migrationId}/cancel`)
            loadMigrations()
        } catch (error) {
            console.error('Failed to cancel migration:', error)
        }
    }

    const calculateProgress = (migration: Migration): { progress: number; completed: number; total: number } => {
        if (!migration.start_date || !migration.end_date || migration.status === 'Completed') {
            return { progress: 100, completed: 0, total: 0 }
        }
        if (migration.status === 'Failed' || migration.status === 'Cancelled') {
            return { progress: 0, completed: 0, total: 0 }
        }

        const start = dayjs(migration.start_date)
        const end = dayjs(migration.end_date)
        const now = dayjs()

        const totalHours = end.diff(start, 'hour')
        const elapsedHours = now.diff(start, 'hour')

        return {
            progress: Math.min(Math.max((elapsedHours / totalHours) * 100, 0), 100),
            completed: Math.min(elapsedHours, totalHours),
            total: totalHours,
        }
    }

    return managedMigrationId ? (
        <ManagedMigration />
    ) : (
        <>
            <PageHeader
                caption="Import data from other analytics providers"
                buttons={
                    <LemonButton
                        data-attr="new-managed-migration"
                        to={urls.managedMigrationNew()}
                        type="primary"
                        icon={<IconPlusSmall />}
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
                        dataIndex: 'source',
                        render: (_, migration) => (
                            <div className="flex items-center gap-2">
                                <img
                                    src={`https://${migration.source}.com/favicon.ico`}
                                    alt={migration.source}
                                    className="w-4 h-4"
                                />
                                {migration.source.charAt(0).toUpperCase() + migration.source.slice(1)}
                            </div>
                        ),
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (_, migration) => <StatusTag status={migration.status} />,
                    },
                    {
                        title: 'Start Date',
                        dataIndex: 'start_date',
                        render: (_, migration) => (
                            <div className="whitespace-nowrap">
                                {migration.start_date ? dayjs(migration.start_date).format('YYYY-MM-DD HH:mm') : '-'}
                            </div>
                        ),
                    },
                    {
                        title: 'End Date',
                        dataIndex: 'end_date',
                        render: (_, migration) => (
                            <div className="whitespace-nowrap">
                                {migration.end_date ? dayjs(migration.end_date).format('YYYY-MM-DD HH:mm') : '-'}
                            </div>
                        ),
                    },
                    {
                        title: 'Progress',
                        dataIndex: 'progress',
                        render: (_, migration) => {
                            const { progress, completed, total } = calculateProgress(migration)
                            return (
                                <div className="flex flex-col gap-1">
                                    <LemonProgress
                                        percent={progress}
                                        strokeColor={migration.status === 'Failed' ? 'var(--danger)' : undefined}
                                    />
                                    <span className="text-xs text-muted">
                                        {migration.status === 'Completed'
                                            ? 'Complete'
                                            : migration.status === 'Failed'
                                            ? 'Failed'
                                            : migration.status === 'Cancelled'
                                            ? 'Cancelled'
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
                        render: function Render(created_at) {
                            return created_at ? (
                                <div className="whitespace-nowrap text-right">
                                    <TZLabel time={created_at} />
                                </div>
                            ) : (
                                <span className="text-secondary">—</span>
                            )
                        },
                        align: 'right',
                    },
                    {
                        title: 'Error',
                        dataIndex: 'error',
                        render: (_, migration) => migration.error || '-',
                    },
                    {
                        title: 'Actions',
                        key: 'actions',
                        render: (_, migration: Migration): JSX.Element | null =>
                            migration.status === 'Running' || migration.status === 'Starting' ? (
                                <LemonButton
                                    status="danger"
                                    size="small"
                                    onClick={() => {
                                        void handleCancel(migration.id)
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                            ) : null,
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

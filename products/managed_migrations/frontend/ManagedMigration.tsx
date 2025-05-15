import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { LemonTable, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { managedMigrationLogic } from './managedMigrationLogic'

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
                    ]}
                />
            </LemonField>

            <LemonField name="apiKey" label="API Key">
                <LemonInput type="password" />
            </LemonField>

            <LemonField name="secretKey" label="Secret Key">
                <LemonInput type="password" />
            </LemonField>

            <div className="flex gap-4">
                <LemonField name="startDate" label="Start Date" className="flex-1">
                    <LemonCalendarSelectInput
                        granularity="minute"
                        value={managedMigration.startDate ? dayjs(managedMigration.startDate) : null}
                        onChange={(date) =>
                            setManagedMigrationValue('startDate', date?.format('YYYY-MM-DD HH:mm:ss') || '')
                        }
                    />
                </LemonField>

                <LemonField name="endDate" label="End Date" className="flex-1">
                    <LemonCalendarSelectInput
                        granularity="minute"
                        value={managedMigration.endDate ? dayjs(managedMigration.endDate) : null}
                        onChange={(date) =>
                            setManagedMigrationValue('endDate', date?.format('YYYY-MM-DD HH:mm:ss') || '')
                        }
                    />
                </LemonField>
            </div>

            <div className="flex flex-col gap-2">
                <LemonField name="eventNamesMode" label="Events">
                    <LemonSelect
                        options={[
                            { value: 'all', label: 'Import all events' },
                            { value: 'allow', label: 'Only import these events' },
                            { value: 'deny', label: "Don't import these events" },
                        ]}
                    />
                </LemonField>

                {managedMigration.eventNamesMode !== 'all' && (
                    <LemonField name="eventNames">
                        <LemonInputSelect
                            mode="multiple"
                            placeholder="Enter event names"
                            value={managedMigration.eventNames}
                            onChange={(value) => setManagedMigrationValue('eventNames', value)}
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

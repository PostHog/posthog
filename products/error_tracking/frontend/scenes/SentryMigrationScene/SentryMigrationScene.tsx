import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCalendarSelectInput,
    LemonCard,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { ErrorTrackingMigrationApi } from '../../generated/api.schemas'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export const scene: SceneExport = {
    component: SentryMigrationScene,
    logic: sentryMigrationLogic,
}

const STATUS_LABELS: Record<ErrorTrackingMigrationApi['status'], string> = {
    created: 'Starting',
    syncing: 'Syncing from Sentry',
    importing: 'Importing events',
    finalizing: 'Syncing issue statuses',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
}

const ACTIVE_STATUSES: ErrorTrackingMigrationApi['status'][] = ['created', 'syncing', 'importing', 'finalizing']

export function SentryMigrationScene(): JSX.Element {
    const enabled = useFeatureFlag('ERROR_TRACKING_SENTRY_MIGRATION')

    if (!enabled) {
        return (
            <LemonBanner type="info" className="mt-4">
                Migrating from Sentry is not available for this project yet.
            </LemonBanner>
        )
    }
    return <SentryMigrationContent />
}

function SentryMigrationContent(): JSX.Element {
    const { latestMigration } = useValues(sentryMigrationLogic)

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <div>
                <h1 className="text-2xl font-bold">Migrate from Sentry</h1>
                <p className="text-secondary">
                    Import your Sentry issues and events into PostHog error tracking, then switch your code over to the
                    PostHog SDK.
                </p>
            </div>
            {latestMigration ? <MigrationStatusCard migration={latestMigration} /> : null}
            {!latestMigration || !ACTIVE_STATUSES.includes(latestMigration.status) ? <StartMigrationCard /> : null}
            <CodeMigrationCard />
        </div>
    )
}

function StartMigrationCard(): JSX.Element {
    const { sentrySources, sentrySourcesLoading, selectedSourceId, orgSlug, dateFrom, migrationStarting } =
        useValues(sentryMigrationLogic)
    const { setSelectedSourceId, setOrgSlug, setDateFrom, startMigration } = useActions(sentryMigrationLogic)

    return (
        <LemonCard className="flex flex-col gap-4" hoverEffect={false}>
            <div>
                <h2 className="text-lg font-semibold mb-0">Import your Sentry data</h2>
                <p className="text-secondary mb-0">
                    The import reads from a Sentry data warehouse source with the <code>issues</code> and{' '}
                    <code>issue_events</code> schemas enabled.
                </p>
            </div>
            {sentrySources.length === 0 && !sentrySourcesLoading ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Connect Sentry',
                        to: '/data-warehouse/new-source?kind=sentry',
                    }}
                >
                    No Sentry source is connected yet. Connect one with your Sentry auth token and organization slug,
                    enable the <code>issues</code> and <code>issue_events</code> schemas, then come back here.
                </LemonBanner>
            ) : (
                <>
                    <div className="flex flex-col gap-1">
                        <label className="font-semibold">Sentry source</label>
                        <LemonSelect
                            placeholder="Select a Sentry source"
                            loading={sentrySourcesLoading}
                            value={selectedSourceId}
                            onChange={(value) => setSelectedSourceId(value)}
                            options={sentrySources.map((source) => ({
                                value: source.id,
                                label: source.prefix ? `Sentry (${source.prefix})` : 'Sentry',
                            }))}
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="font-semibold">Sentry organization slug</label>
                        <LemonInput
                            placeholder="my-org"
                            value={orgSlug}
                            onChange={setOrgSlug}
                            data-attr="sentry-migration-org-slug"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="font-semibold">Import events from (optional)</label>
                        <LemonCalendarSelectInput
                            value={dateFrom ? dayjs(dateFrom) : null}
                            onChange={(value) => setDateFrom(value ? value.toISOString() : null)}
                            placeholder="Everything Sentry retains"
                            clearable
                        />
                    </div>
                    <div>
                        <LemonButton
                            type="primary"
                            onClick={startMigration}
                            loading={migrationStarting}
                            disabledReason={
                                !selectedSourceId
                                    ? 'Select a Sentry source'
                                    : !orgSlug
                                      ? 'Enter the Sentry organization slug'
                                      : undefined
                            }
                        >
                            Start import
                        </LemonButton>
                    </div>
                </>
            )}
        </LemonCard>
    )
}

function MigrationStatusCard({ migration }: { migration: ErrorTrackingMigrationApi }): JSX.Element {
    const { cancelMigration } = useActions(sentryMigrationLogic)
    const isActive = ACTIVE_STATUSES.includes(migration.status)
    const eventsTotal = migration.state.events_total ?? 0
    const eventsEmitted = migration.state.events_emitted ?? 0
    const eventsDropped = migration.state.events_dropped ?? 0

    return (
        <LemonCard className="flex flex-col gap-3" hoverEffect={false}>
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold mb-0">Import from {migration.config.org_slug ?? 'Sentry'}</h2>
                    <LemonTag
                        type={
                            migration.status === 'completed'
                                ? 'success'
                                : migration.status === 'failed'
                                  ? 'danger'
                                  : isActive
                                    ? 'highlight'
                                    : 'default'
                        }
                    >
                        {STATUS_LABELS[migration.status]}
                    </LemonTag>
                </div>
                {isActive ? (
                    <LemonButton type="secondary" status="danger" onClick={() => cancelMigration(migration.id)}>
                        Cancel
                    </LemonButton>
                ) : null}
            </div>
            {eventsTotal > 0 ? (
                <>
                    <LemonProgress percent={Math.min(100, Math.round((eventsEmitted / eventsTotal) * 100))} />
                    <div className="text-secondary">
                        {eventsEmitted.toLocaleString()} of {eventsTotal.toLocaleString()} events imported
                        {eventsDropped > 0
                            ? ` (${eventsDropped.toLocaleString()} dropped, check your exceptions quota)`
                            : ''}
                    </div>
                </>
            ) : null}
            {migration.status === 'failed' && migration.latest_error ? (
                <LemonBanner type="error">{migration.latest_error}</LemonBanner>
            ) : null}
            {migration.status === 'completed' ? (
                <LemonBanner type="success" action={{ children: 'View your issues', to: urls.errorTracking() }}>
                    Import complete. Your Sentry issues now live in error tracking, keeping their grouping, statuses and
                    stack traces.
                </LemonBanner>
            ) : null}
        </LemonCard>
    )
}

function CodeMigrationCard(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand('sentry')

    if (!isCloudOrDev) {
        return <></>
    }
    return (
        <LemonCard className="flex flex-col gap-3" hoverEffect={false}>
            <div>
                <h2 className="text-lg font-semibold mb-0">Migrate your code</h2>
                <p className="text-secondary mb-0">
                    Run the setup agent from the root of your project. It replaces the Sentry SDK with PostHog error
                    tracking, migrates your <code>captureException</code> calls and source map uploads, and writes a
                    report of what changed.
                </p>
            </div>
            <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
            <LemonDivider className="my-0" />
            <p className="text-secondary mb-0">
                Once events flow from the PostHog SDK, remove your <code>SENTRY_DSN</code> environment variables and
                wind down your Sentry alert rules. See the{' '}
                <Link to="https://posthog.com/docs/error-tracking">error tracking docs</Link> for details.
            </p>
        </LemonCard>
    )
}

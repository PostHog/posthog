import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { ImportWizardStepActions } from './ImportWizardStepActions'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { SentryMigrationProjectPicker } from './SentryMigrationProjectPicker'

export function SentryProjectStep(): JSX.Element {
    const { projects, selectedProjectKey, selectedProject, items, itemsLoading, previewFailed } =
        useValues(sentryMigrationLogic)
    const { disconnect, loadPreview, goToNextStep, goToPreviousStep } = useActions(sentryMigrationLogic)
    const hasItems = !!selectedProject && !itemsLoading && !!items && items.length > 0

    return (
        <>
            <ImportWizardStepHeading
                title="Choose a Sentry project"
                description="PostHog reads the filters and rate limits of this project. Nothing changes until you import."
            />
            {projects && projects.length === 0 ? (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Use another token',
                        onClick: disconnect,
                        'data-attr': 'error-tracking-sentry-migration-disconnect',
                    }}
                >
                    This token can't see any Sentry projects. Check that its user is a member of the organization, then
                    connect again.
                </LemonBanner>
            ) : (
                <>
                    <SentryMigrationProjectPicker />
                    {!selectedProjectKey ? null : itemsLoading ? (
                        <Spinner />
                    ) : previewFailed ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => loadPreview(),
                                'data-attr': 'error-tracking-sentry-migration-retry-preview',
                            }}
                        >
                            Couldn't load this project from Sentry. Try again. If it keeps failing, the token may have
                            expired, so go back and use another token.
                        </LemonBanner>
                    ) : items === null ? (
                        <Spinner />
                    ) : items.length === 0 ? (
                        <LemonBanner type="info">
                            This Sentry project has no filters or rate limits that PostHog can import.
                        </LemonBanner>
                    ) : (
                        <p className="text-sm mb-0">
                            {`Found ${items.length} ${items.length === 1 ? 'setting' : 'settings'} to review in this project.`}
                        </p>
                    )}
                </>
            )}
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <LemonButton
                    type="primary"
                    onClick={goToNextStep}
                    disabledReason={hasItems ? undefined : 'Choose a project with settings to import'}
                    data-attr="error-tracking-import-next"
                >
                    Continue
                </LemonButton>
            </ImportWizardStepActions>
        </>
    )
}

import { useActions, useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Spinner, Text } from '@posthog/quill'

import { ImportWizardStepActions } from './ImportWizardStepActions'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { SentryMigrationProjectPicker } from './SentryMigrationProjectPicker'

export function SentryProjectStep(): JSX.Element {
    const { projects, selectedProjectKey, items, itemsLoading, previewFailed } = useValues(sentryMigrationLogic)
    const { disconnect, loadPreview, goToNextStep, goToPreviousStep } = useActions(sentryMigrationLogic)
    const hasItems = !itemsLoading && !!items && items.length > 0

    return (
        <>
            <ImportWizardStepHeading
                title="Choose a Sentry project"
                description="PostHog reads the filters and rate limits of this project. Nothing changes until you import."
            />
            {projects && projects.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>No Sentry projects found</EmptyTitle>
                        <EmptyDescription>
                            This token can't see any Sentry projects. Check that its user is a member of the
                            organization, then connect again.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            onClick={disconnect}
                            data-attr="error-tracking-sentry-migration-disconnect"
                        >
                            Use another token
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : (
                <>
                    <SentryMigrationProjectPicker />
                    {!selectedProjectKey ? null : itemsLoading ? (
                        <Spinner />
                    ) : previewFailed ? (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>Couldn't load this project from Sentry</EmptyTitle>
                                <EmptyDescription>
                                    Try again. If it keeps failing, the token may have expired, so go back and use
                                    another token.
                                </EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    onClick={() => loadPreview()}
                                    data-attr="error-tracking-sentry-migration-retry-preview"
                                >
                                    Try again
                                </Button>
                            </EmptyContent>
                        </Empty>
                    ) : items === null ? (
                        <Spinner />
                    ) : items.length === 0 ? (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>Nothing to import</EmptyTitle>
                                <EmptyDescription>
                                    This Sentry project has no filters or rate limits that PostHog can import.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <Text size="sm" className="m-0">
                            {`Found ${items.length} ${items.length === 1 ? 'setting' : 'settings'} to review in this project.`}
                        </Text>
                    )}
                </>
            )}
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <Button
                    variant="primary"
                    onClick={goToNextStep}
                    disabledReason={hasItems ? undefined : 'Choose a project with settings to import'}
                    data-attr="error-tracking-import-next"
                >
                    Continue
                </Button>
            </ImportWizardStepActions>
        </>
    )
}

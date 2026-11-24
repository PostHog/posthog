import { useActions, useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription, Spinner, Text } from '@posthog/quill'

import { QuillImportWizardStepActions } from './QuillImportWizardStepActions'
import { QuillImportWizardStepHeading } from './QuillImportWizardStepHeading'
import { QuillSentryMigrationProjectPicker } from './QuillSentryMigrationProjectPicker'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function QuillSentryProjectStep(): JSX.Element {
    const { projects, selectedProjectKey, selectedProject, items, itemsLoading, previewFailed, omittedFilterNames } =
        useValues(sentryMigrationLogic)
    const { disconnect, loadPreview, goToNextStep, goToPreviousStep } = useActions(sentryMigrationLogic)
    const hasItems = !!selectedProject && !itemsLoading && !!items && items.length > 0
    const hasPreview = !!selectedProjectKey && !itemsLoading && !previewFailed && items !== null

    return (
        <>
            <QuillImportWizardStepHeading
                title="Choose a Sentry project"
                description="PostHog reads the filters and rate limits of this project. Nothing changes until you import."
            />
            {projects && projects.length === 0 ? (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            This token can't see any Sentry projects. Check that its user is a member of the
                            organization, then connect again.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            onClick={disconnect}
                            data-attr="error-tracking-sentry-migration-disconnect"
                        >
                            Use another token
                        </Button>
                    </ItemActions>
                </Item>
            ) : (
                <>
                    <QuillSentryMigrationProjectPicker />
                    {!selectedProjectKey ? null : itemsLoading ? (
                        <Spinner />
                    ) : previewFailed ? (
                        <Item tone="destructive" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Couldn't load this project from Sentry. Try again. If it keeps failing, the token
                                    may have expired, so go back and use another token.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button
                                    variant="outline"
                                    onClick={() => loadPreview()}
                                    data-attr="error-tracking-sentry-migration-retry-preview"
                                >
                                    Try again
                                </Button>
                            </ItemActions>
                        </Item>
                    ) : items === null ? (
                        <Spinner />
                    ) : items.length === 0 ? (
                        <Item tone="info" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    This Sentry project has no filters or rate limits that PostHog can import.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : (
                        <Text size="xs" render={<p className="m-0" />}>
                            {`Found ${items.length} ${items.length === 1 ? 'setting' : 'settings'} to review in this project.`}
                        </Text>
                    )}
                    {hasPreview && omittedFilterNames.length > 0 && (
                        <Text
                            size="xs"
                            render={<p className="m-0" />}
                            data-attr="error-tracking-sentry-migration-omitted-filters"
                        >
                            {`PostHog can't import these Sentry filters, so exceptions they dropped in Sentry will reach PostHog: ${omittedFilterNames.join(', ')}.`}
                        </Text>
                    )}
                </>
            )}
            <QuillImportWizardStepActions onBack={goToPreviousStep}>
                <Button
                    variant="primary"
                    onClick={goToNextStep}
                    disabledReason={hasItems ? undefined : 'Choose a project with settings to import'}
                    data-attr="error-tracking-import-next"
                >
                    Continue
                </Button>
            </QuillImportWizardStepActions>
        </>
    )
}

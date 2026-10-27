import { useActions, useValues } from 'kea'

import {
    Button,
    CardGroup,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Spinner,
    Text,
} from '@posthog/quill'

import type { SentryMigrationCategoryEnumApi } from '../../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { SentryMigrationItemCard } from './SentryMigrationItemCard'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { SentryMigrationProjectPicker } from './SentryMigrationProjectPicker'
import { isSelectable } from './sentryMigrationSelection'

const CATEGORIES: Record<SentryMigrationCategoryEnumApi, { title: string; description: string }> = {
    rate_limit: { title: 'Rate limits', description: 'Sets the rate limit for this project.' },
    error_message: {
        title: 'Error message filters',
        description: 'Each one becomes a manual suppression rule.',
    },
    release: { title: 'Release filters', description: 'Each one becomes a manual suppression rule.' },
    inbound_filter: {
        title: 'Inbound filters',
        description: 'Each one turns on the matching automatic suppression rule, which PostHog keeps up to date.',
    },
}

export function SentryImportStep(): JSX.Element {
    const { projects, selectedProjectKey, items, itemsLoading, previewFailed, selectedItemIds, importResultLoading } =
        useValues(sentryMigrationLogic)
    const { toggleItem, applyImport, disconnect, loadPreview } = useActions(sentryMigrationLogic)
    const editAccessDisabledReason = errorTrackingEditAccessDisabledReason()
    const selectableCount = (items ?? []).filter(isSelectable).length

    return (
        <>
            <ImportWizardStepHeading
                title="Choose what to import"
                description="Pick a Sentry project, then select the settings to bring over. Nothing changes until you import."
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
                    <div className="flex flex-wrap items-end gap-2">
                        <SentryMigrationProjectPicker />
                        <Button
                            variant="outline"
                            onClick={disconnect}
                            data-attr="error-tracking-sentry-migration-disconnect"
                        >
                            Use another token
                        </Button>
                    </div>

                    {!selectedProjectKey ? null : itemsLoading ? (
                        <Spinner />
                    ) : previewFailed ? (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>Couldn't load this project from Sentry</EmptyTitle>
                                <EmptyDescription>
                                    Try again. If it keeps failing, the token may have expired, so use another token.
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
                                    This Sentry project has its default inbound filters off, and no custom error message
                                    or release filters.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <>
                            {(Object.keys(CATEGORIES) as SentryMigrationCategoryEnumApi[]).map((category) => {
                                const categoryItems = items.filter((item) => item.category === category)
                                if (categoryItems.length === 0) {
                                    return null
                                }
                                return (
                                    <div key={category} className="flex flex-col gap-2">
                                        <div className="flex flex-col gap-0.5">
                                            <Heading size="sm" render={<h4 className="m-0" />}>
                                                {CATEGORIES[category].title}
                                            </Heading>
                                            <Text size="xs" variant="muted" className="m-0">
                                                {CATEGORIES[category].description}
                                            </Text>
                                        </div>
                                        <CardGroup size="sm">
                                            {categoryItems.map((item) => (
                                                <SentryMigrationItemCard
                                                    key={item.id}
                                                    item={item}
                                                    selected={selectedItemIds.includes(item.id)}
                                                    disabledReason={
                                                        item.fit === 'unsupported'
                                                            ? "PostHog can't import this setting"
                                                            : item.already_in_posthog
                                                              ? item.built_in_filter
                                                                  ? 'This automatic suppression rule is already on'
                                                                  : 'This project already has this setting'
                                                              : null
                                                    }
                                                    onToggle={() => toggleItem(item.id)}
                                                />
                                            ))}
                                        </CardGroup>
                                    </div>
                                )
                            })}
                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    variant="primary"
                                    onClick={applyImport}
                                    loading={importResultLoading}
                                    disabledReason={
                                        editAccessDisabledReason ??
                                        (selectableCount === 0
                                            ? 'Everything PostHog can import is already in this project'
                                            : selectedItemIds.length === 0
                                              ? 'Select at least one setting to import'
                                              : undefined)
                                    }
                                    data-attr="error-tracking-sentry-migration-import"
                                >
                                    {selectedItemIds.length === 1
                                        ? 'Import 1 setting'
                                        : `Import ${selectedItemIds.length} settings`}
                                </Button>
                                <Text size="xs" variant="muted" className="m-0">
                                    You can change or remove anything you import later, on this page.
                                </Text>
                            </div>
                        </>
                    )}
                </>
            )}
        </>
    )
}

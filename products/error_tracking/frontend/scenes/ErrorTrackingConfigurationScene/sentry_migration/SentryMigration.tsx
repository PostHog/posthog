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
    TooltipProvider,
} from '@posthog/quill'

import type { SentryMigrationCategoryEnumApi } from '../../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { SentryMigrationConnectForm } from './SentryMigrationConnectForm'
import { SentryMigrationItemCard } from './SentryMigrationItemCard'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { SentryMigrationProjectPicker } from './SentryMigrationProjectPicker'
import { isSelectable } from './sentryMigrationSelection'

const CATEGORY_TITLES: Record<SentryMigrationCategoryEnumApi, string> = {
    rate_limit: 'Rate limits',
    error_message: 'Error message filters',
    release: 'Release filters',
    inbound_filter: 'Inbound filters',
}

export function SentryMigration(): JSX.Element {
    const {
        isConnected,
        projects,
        selectedProjectKey,
        items,
        itemsLoading,
        previewFailed,
        selectedItemIds,
        importResultLoading,
    } = useValues(sentryMigrationLogic)
    const { toggleItem, applyImport, disconnect, loadPreview } = useActions(sentryMigrationLogic)
    const editAccessDisabledReason = errorTrackingEditAccessDisabledReason()
    const selectableCount = (items ?? []).filter(isSelectable).length

    return (
        <TooltipProvider>
            <div className="flex flex-col gap-4" data-quill>
                {!isConnected ? (
                    <SentryMigrationConnectForm />
                ) : projects && projects.length === 0 ? (
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
                                        Try again. If it keeps failing, the token may have expired, so use another
                                        token.
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
                                        This Sentry project has its default inbound filters off, and no custom error
                                        message or release filters.
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        ) : (
                            <>
                                {(Object.keys(CATEGORY_TITLES) as SentryMigrationCategoryEnumApi[]).map((category) => {
                                    const categoryItems = items.filter((item) => item.category === category)
                                    if (categoryItems.length === 0) {
                                        return null
                                    }
                                    return (
                                        <div key={category} className="flex flex-col gap-2">
                                            <Heading size="sm" render={<h4 className="m-0" />}>
                                                {CATEGORY_TITLES[category]}
                                            </Heading>
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
                                                                  ? 'This project already has this setting'
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
                                        Imported filters become suppression rules. You can edit or delete them
                                        afterwards.
                                    </Text>
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>
        </TooltipProvider>
    )
}

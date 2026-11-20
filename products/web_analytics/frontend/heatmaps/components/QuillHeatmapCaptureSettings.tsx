import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { HeatmapCapturePageApi, HeatmapCaptureSettingsApi } from '../../generated/api.schemas'
import { HeatmapCaptureMode } from './heatmapCaptureSettingsLogic'

export function QuillHeatmapCaptureSettings({
    settings,
    settingsLoading,
    captureMode,
    urlAllowlist,
    hasChanges,
    saveError,
    canCaptureAllUrls,
    captureUrlLimit,
    disabledPages,
    pagesLoading,
    pagesError,
    restrictedReason,
    onCaptureModeChange,
    onUrlAllowlistChange,
    onRetryPages,
    onSave,
}: {
    settings: HeatmapCaptureSettingsApi
    settingsLoading: boolean
    captureMode: HeatmapCaptureMode
    urlAllowlist: string[]
    hasChanges: boolean
    saveError: string | null
    canCaptureAllUrls: boolean
    captureUrlLimit: number | null
    disabledPages: HeatmapCapturePageApi[]
    pagesLoading: boolean
    pagesError: boolean
    restrictedReason: string | null
    onCaptureModeChange: (captureMode: HeatmapCaptureMode) => void
    onUrlAllowlistChange: (urls: string[]) => void
    onRetryPages: () => void
    onSave: () => void
}): JSX.Element {
    const isAllowlist = captureMode === 'url_allowlist'
    const emptyAllowlist = isAllowlist && urlAllowlist.length === 0
    const atUrlLimit = captureUrlLimit != null && urlAllowlist.length >= captureUrlLimit

    return (
        <div className="flex max-w-160 flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                Choose which pages send heatmap data. Capture from every page, or only from the URLs you list. Data from
                pages that are not covered is not collected.
            </Text>

            {!canCaptureAllUrls && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Your plan captures heatmaps on up to {captureUrlLimit} URLs. Pick the pages that matter
                            most, or upgrade to capture every page.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.organizationBilling()} />}
                        >
                            Upgrade
                        </Button>
                    </ItemActions>
                </Item>
            )}

            {settings.enforcement_enabled ? (
                emptyAllowlist && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                No URLs are listed, so no heatmap data is being collected. Add at least one URL
                                {canCaptureAllUrls ? ', or choose Allow all URLs' : ''}.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )
            ) : (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            These rules are not enforced yet. Heatmap data is still collected from every page for now,
                            but that will change. Set them up so capture keeps working when they take effect.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            <Field>
                <FieldLabel>Pages to capture</FieldLabel>
                <ToggleGroup
                    variant="outline"
                    aria-label="Pages to capture"
                    value={[captureMode]}
                    onValueChange={(next: string[]) => {
                        const picked = next[0] as HeatmapCaptureMode | undefined
                        if (picked) {
                            onCaptureModeChange(picked)
                        }
                    }}
                    className="w-fit"
                >
                    <ToggleGroupItem value="url_allowlist" disabledReason={restrictedReason}>
                        Only listed URLs
                    </ToggleGroupItem>
                    <ToggleGroupItem
                        value="all"
                        disabledReason={
                            restrictedReason ?? (canCaptureAllUrls ? undefined : 'Upgrade to capture all pages')
                        }
                    >
                        Allow all URLs
                    </ToggleGroupItem>
                </ToggleGroup>
            </Field>

            {isAllowlist && (
                <Field>
                    <FieldLabel>Allowed URLs</FieldLabel>
                    <TagsCombobox
                        value={urlAllowlist}
                        onChange={onUrlAllowlistChange}
                        customValueNoun="URL"
                        dataAttr="heatmap-capture-url-allowlist"
                        // Past the plan limit a new URL would be dropped silently, so creating one turns off.
                        allowCustomValues={!atUrlLimit}
                        placeholder={
                            atUrlLimit ? `Limit of ${captureUrlLimit} URLs reached` : 'https://example.com/pricing'
                        }
                        disabled={settingsLoading}
                        disabledReason={restrictedReason}
                        className="w-full"
                    />
                    <FieldDescription>
                        {captureUrlLimit != null ? `Your plan captures up to ${captureUrlLimit} URLs. ` : ''}
                        Enter full URLs. Use <code>*</code> to match any characters, for example{' '}
                        <code>https://example.com/docs/*</code>.
                    </FieldDescription>
                </Field>
            )}

            {!canCaptureAllUrls && isAllowlist && (
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Pages that will stop capturing
                    </Heading>
                    {pagesLoading ? (
                        <Skeleton className="h-16" />
                    ) : pagesError ? (
                        <Item tone="destructive" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Could not check which pages your listed URLs cover. Try again.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button variant="outline" onClick={onRetryPages}>
                                    Retry
                                </Button>
                            </ItemActions>
                        </Item>
                    ) : disabledPages.length === 0 ? (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Your listed URLs cover every page we currently collect heatmaps on.
                        </Text>
                    ) : (
                        <Table>
                            <TableBody>
                                {disabledPages.map((page) => (
                                    <TableRow key={page.url}>
                                        <TableCell className="max-w-0 truncate">{page.url}</TableCell>
                                        <TableCell className="text-right whitespace-nowrap text-muted-foreground">
                                            {page.count.toLocaleString()} events
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </div>
            )}

            {saveError && (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Could not save. Check that each entry is a full http or https URL, then try again.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {!restrictedReason && (
                <div>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={settingsLoading}
                        disabledReason={!hasChanges ? 'No changes to save' : undefined}
                    >
                        Save capture URLs
                    </Button>
                </div>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Field,
    FieldError,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceAccess } from './SpaceAccess'
import { SpaceMembers } from './SpaceMembers'
import { SpaceRepositories } from './SpaceRepositories'
import {
    AUTO_ARCHIVE_MAX_DAYS,
    AUTO_ARCHIVE_MIN_DAYS,
    AUTO_ARCHIVE_PRESET_DAYS,
    AutoArchiveSelection,
    spaceSceneLogic,
} from './spaceSceneLogic'
import { SpaceSettingsSection } from './SpaceSettingsSection'

const AUTO_ARCHIVE_OPTIONS: { value: AutoArchiveSelection; label: string }[] = [
    { value: null, label: 'Never' },
    ...AUTO_ARCHIVE_PRESET_DAYS.map((days) => ({ value: days, label: `After ${days} ${days === 1 ? 'day' : 'days'}` })),
    { value: 'custom', label: 'Custom…' },
]

/** Keeps the row's label on the left until the control no longer fits beside it, then stacks the row. */
const ROW_CONTENT_CLASS = 'min-w-56'

export function SpaceSettings({ id }: { id: string }): JSX.Element {
    const {
        space,
        savingSpace,
        nameDraft,
        nameError,
        renameDisabledReason,
        deleteDisabledReason,
        autoArchiveSelection,
        autoArchiveDisabledReason,
        autoArchiveCustomDays,
        autoArchiveCustomError,
        autoArchiveCustomSaveDisabledReason,
    } = useValues(spaceSceneLogic({ id }))
    const {
        setNameDraft,
        commitName,
        deleteSpace,
        setAutoArchiveSelection,
        setAutoArchiveCustomDays,
        saveAutoArchiveCustomDays,
    } = useActions(spaceSceneLogic({ id }))

    if (!space) {
        return (
            <div className="-mx-4" aria-busy="true">
                <div className="flex min-h-11 items-center border-b border-border px-6 py-2">
                    <Skeleton className="h-4 w-80 max-w-full" />
                </div>
                <div className="flex w-full max-w-200 flex-col gap-7 px-6 pt-6 pb-8">
                    {[1, 2, 3].map((section) => (
                        <div key={section} className="flex flex-col gap-2">
                            <Skeleton className="h-4 w-28" />
                            <Skeleton className="h-14 w-full" />
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="-mx-4">
            <div className="flex min-h-11 items-center border-b border-border px-6 py-2">
                <Text size="xs" variant="muted" className="min-w-0">
                    The name, repositories, and who can see this space. Changes save as you make them.
                </Text>
            </div>
            <div className="flex w-full max-w-200 flex-col gap-7 px-6 pt-6 pb-8">
                <SpaceSettingsSection label="General">
                    <ItemGroup combined>
                        <Item variant="outline" size="sm">
                            <ItemContent className={ROW_CONTENT_CLASS}>
                                <ItemTitle id="space-settings-name-label">Name</ItemTitle>
                                <ItemDescription id="space-settings-name-description">
                                    {renameDisabledReason ?? 'Shown in the sidebar and at the top of this space.'}
                                </ItemDescription>
                            </ItemContent>
                            <Field className="w-64 max-w-full" data-invalid={!!nameError || undefined}>
                                <Input
                                    value={renameDisabledReason ? spaceLabel(space) : (nameDraft ?? space.name)}
                                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                        setNameDraft(event.target.value)
                                    }
                                    onBlur={() => commitName()}
                                    onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                                        if (event.key === 'Enter') {
                                            commitName()
                                        } else if (event.key === 'Escape') {
                                            setNameDraft(null)
                                        }
                                    }}
                                    disabled={!!renameDisabledReason}
                                    aria-labelledby="space-settings-name-label"
                                    aria-describedby="space-settings-name-description"
                                    aria-invalid={!!nameError || undefined}
                                    data-attr="today-space-settings-name"
                                />
                                {nameError && <FieldError>{nameError}</FieldError>}
                            </Field>
                        </Item>
                    </ItemGroup>
                </SpaceSettingsSection>

                <SpaceRepositories id={id} />
                <SpaceAccess id={id} />
                <SpaceMembers id={id} />

                <SpaceSettingsSection label="Sessions">
                    <ItemGroup combined>
                        <Item variant="outline" size="sm">
                            <ItemContent className={ROW_CONTENT_CLASS}>
                                <ItemTitle id="space-auto-archive-label">Auto-archive</ItemTitle>
                                <ItemDescription>
                                    Archive sessions after a period with no activity. New messages and runs start the
                                    period again.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Tooltip disabled={!autoArchiveDisabledReason || savingSpace}>
                                    <TooltipTrigger render={<div />}>
                                        <Select<AutoArchiveSelection>
                                            items={AUTO_ARCHIVE_OPTIONS}
                                            value={autoArchiveSelection}
                                            onValueChange={(selection: AutoArchiveSelection) =>
                                                setAutoArchiveSelection(selection)
                                            }
                                            disabled={!!autoArchiveDisabledReason}
                                        >
                                            <SelectTrigger
                                                aria-labelledby="space-auto-archive-label"
                                                data-attr="today-space-settings-auto-archive"
                                            >
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {AUTO_ARCHIVE_OPTIONS.map((option) => (
                                                    <SelectItem key={option.label} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </TooltipTrigger>
                                    <TooltipContent>{autoArchiveDisabledReason}</TooltipContent>
                                </Tooltip>
                            </ItemActions>
                        </Item>
                        {autoArchiveSelection === 'custom' && (
                            <Item variant="outline" size="sm">
                                <ItemContent className={ROW_CONTENT_CLASS}>
                                    <ItemTitle id="space-auto-archive-custom-days-label">Days of inactivity</ItemTitle>
                                    {autoArchiveCustomError ? (
                                        <FieldError>{autoArchiveCustomError}</FieldError>
                                    ) : (
                                        <ItemDescription>
                                            Choose a value from {AUTO_ARCHIVE_MIN_DAYS} to {AUTO_ARCHIVE_MAX_DAYS} days.
                                        </ItemDescription>
                                    )}
                                </ItemContent>
                                <Field
                                    orientation="horizontal"
                                    className="w-auto"
                                    data-invalid={!!autoArchiveCustomError || undefined}
                                >
                                    <NumberFieldRoot
                                        className="w-24"
                                        value={autoArchiveCustomDays}
                                        onValueChange={(days: number | null) => setAutoArchiveCustomDays(days)}
                                        min={AUTO_ARCHIVE_MIN_DAYS}
                                        max={AUTO_ARCHIVE_MAX_DAYS}
                                        step={1}
                                        allowOutOfRange
                                        disabled={!!autoArchiveDisabledReason}
                                    >
                                        <NumberFieldGroup>
                                            <NumberFieldInput
                                                aria-labelledby="space-auto-archive-custom-days-label"
                                                aria-invalid={!!autoArchiveCustomError || undefined}
                                                data-attr="today-space-settings-auto-archive-custom-days"
                                            />
                                        </NumberFieldGroup>
                                    </NumberFieldRoot>
                                    <Tooltip disabled={!autoArchiveCustomSaveDisabledReason || savingSpace}>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    variant="outline"
                                                    loading={savingSpace}
                                                    disabled={!!autoArchiveCustomSaveDisabledReason}
                                                    onClick={() => saveAutoArchiveCustomDays()}
                                                    data-attr="today-space-settings-auto-archive-custom-save"
                                                />
                                            }
                                        >
                                            Save
                                        </TooltipTrigger>
                                        <TooltipContent>{autoArchiveCustomSaveDisabledReason}</TooltipContent>
                                    </Tooltip>
                                </Field>
                            </Item>
                        )}
                    </ItemGroup>
                    <Text size="xs" variant="muted" className="px-0.5">
                        Pinned and running sessions, and sessions someone is viewing, are never archived. In shared
                        spaces, only project admins can change this.
                    </Text>
                </SpaceSettingsSection>

                <SpaceSettingsSection label="Danger zone">
                    <ItemGroup combined>
                        <Item variant="outline" size="sm">
                            <ItemContent className={ROW_CONTENT_CLASS}>
                                <ItemTitle>Delete space</ItemTitle>
                                <ItemDescription>
                                    This removes the space for everyone. It only works when the space has no sessions or
                                    canvases.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <AlertDialog>
                                    <Tooltip disabled={!deleteDisabledReason}>
                                        <TooltipTrigger
                                            render={
                                                <AlertDialogTrigger
                                                    render={
                                                        <Button
                                                            variant="destructive"
                                                            disabled={!!deleteDisabledReason}
                                                            data-attr="today-space-settings-delete"
                                                        />
                                                    }
                                                />
                                            }
                                        >
                                            Delete space
                                        </TooltipTrigger>
                                        <TooltipContent>{deleteDisabledReason}</TooltipContent>
                                    </Tooltip>
                                    <AlertDialogContent>
                                        <AlertDialogHeader>
                                            <AlertDialogTitle>{`Delete ${spaceLabel(space)}?`}</AlertDialogTitle>
                                            <AlertDialogDescription>
                                                This removes the space for everyone. You can only delete a space that
                                                has no sessions or canvases.
                                            </AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                            <AlertDialogClose render={<Button variant="outline" />}>
                                                Cancel
                                            </AlertDialogClose>
                                            <AlertDialogClose
                                                render={
                                                    <Button
                                                        variant="destructive-outline"
                                                        onClick={() => deleteSpace()}
                                                        data-attr="today-space-settings-delete-confirm"
                                                    />
                                                }
                                            >
                                                Delete
                                            </AlertDialogClose>
                                        </AlertDialogFooter>
                                    </AlertDialogContent>
                                </AlertDialog>
                            </ItemActions>
                        </Item>
                    </ItemGroup>
                </SpaceSettingsSection>
            </div>
        </div>
    )
}

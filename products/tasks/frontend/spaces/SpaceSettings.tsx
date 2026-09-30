import { useActions, useValues } from 'kea'
import { ChangeEvent, useState } from 'react'

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
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
    FieldTitle,
    Input,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceAccess } from './SpaceAccess'
import { SpaceRepositories } from './SpaceRepositories'
import {
    AUTO_ARCHIVE_MAX_DAYS,
    AUTO_ARCHIVE_MIN_DAYS,
    AUTO_ARCHIVE_PRESET_DAYS,
    AutoArchiveSelection,
    spaceSceneLogic,
} from './spaceSceneLogic'

const AUTO_ARCHIVE_OPTIONS: { value: AutoArchiveSelection; label: string }[] = [
    { value: null, label: 'Never' },
    ...AUTO_ARCHIVE_PRESET_DAYS.map((days) => ({ value: days, label: `After ${days} ${days === 1 ? 'day' : 'days'}` })),
    { value: 'custom', label: 'Custom…' },
]

export function SpaceSettings({ id }: { id: string }): JSX.Element | null {
    const {
        space,
        savingSpace,
        autoArchiveSelection,
        autoArchiveDisabledReason,
        autoArchiveCustomDays,
        autoArchiveCustomError,
        autoArchiveCustomSaveDisabledReason,
    } = useValues(spaceSceneLogic({ id }))
    const { updateSpace, deleteSpace, setAutoArchiveSelection, setAutoArchiveCustomDays, saveAutoArchiveCustomDays } =
        useActions(spaceSceneLogic({ id }))
    const [name, setName] = useState(space?.name ?? '')

    if (!space) {
        return null
    }
    const defaultSpace = space.system_role !== null
    const trimmedName = name.trim()
    const renameDisabledReason = defaultSpace
        ? 'Default spaces can’t be renamed'
        : !trimmedName
          ? 'Enter a name'
          : trimmedName === space.name
            ? 'Change the name first'
            : null
    const deleteDisabledReason = defaultSpace
        ? 'Default spaces can’t be deleted'
        : savingSpace
          ? 'Saving your last change'
          : null

    return (
        <FieldGroup className="max-w-160">
            <Field>
                <FieldLabel htmlFor="space-name">Name</FieldLabel>
                <div className="flex flex-wrap gap-2">
                    <Input
                        id="space-name"
                        className="min-w-60 flex-1"
                        value={defaultSpace ? spaceLabel(space) : name}
                        onChange={(event: ChangeEvent<HTMLInputElement>) => setName(event.target.value)}
                        disabled={defaultSpace}
                        data-attr="today-space-settings-name"
                    />
                    <Tooltip disabled={!renameDisabledReason || savingSpace}>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    loading={savingSpace}
                                    disabled={!!renameDisabledReason}
                                    onClick={() => updateSpace({ name: trimmedName })}
                                    data-attr="today-space-settings-rename"
                                />
                            }
                        >
                            Save
                        </TooltipTrigger>
                        <TooltipContent>{renameDisabledReason}</TooltipContent>
                    </Tooltip>
                </div>
                {defaultSpace && <FieldDescription>Default spaces can’t be renamed.</FieldDescription>}
            </Field>
            <Field>
                <FieldTitle>Repositories</FieldTitle>
                <SpaceRepositories id={id} />
                <FieldDescription>Sessions in this space start with these repositories checked out.</FieldDescription>
            </Field>
            <Field>
                <FieldTitle>Access</FieldTitle>
                <SpaceAccess id={id} />
            </Field>
            <Field>
                <FieldLabel htmlFor="space-auto-archive">Auto-archive sessions</FieldLabel>
                <Tooltip disabled={!autoArchiveDisabledReason || savingSpace}>
                    <TooltipTrigger render={<div className="w-fit" />}>
                        <Select<AutoArchiveSelection>
                            items={AUTO_ARCHIVE_OPTIONS}
                            value={autoArchiveSelection}
                            onValueChange={(selection: AutoArchiveSelection) => setAutoArchiveSelection(selection)}
                            disabled={!!autoArchiveDisabledReason}
                        >
                            <SelectTrigger id="space-auto-archive" data-attr="today-space-settings-auto-archive">
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
                <FieldDescription>
                    Sessions with no activity for this long move to the archive. New messages and session runs reset
                    this period. Sessions being viewed, pinned, or actively running are not archived. In shared spaces,
                    only project admins can change this.
                </FieldDescription>
            </Field>
            {autoArchiveSelection === 'custom' && (
                <Field data-invalid={!!autoArchiveCustomError || undefined}>
                    <FieldLabel htmlFor="space-auto-archive-custom-days">Days of inactivity</FieldLabel>
                    <div className="flex flex-wrap gap-2">
                        <NumberFieldRoot
                            id="space-auto-archive-custom-days"
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
                    </div>
                    {autoArchiveCustomError ? (
                        <FieldError>{autoArchiveCustomError}</FieldError>
                    ) : (
                        <FieldDescription>
                            Choose a value from {AUTO_ARCHIVE_MIN_DAYS} to {AUTO_ARCHIVE_MAX_DAYS} days.
                        </FieldDescription>
                    )}
                </Field>
            )}
            <Field>
                <FieldTitle>Delete space</FieldTitle>
                <div>
                    <AlertDialog>
                        <Tooltip disabled={!deleteDisabledReason}>
                            <TooltipTrigger
                                render={
                                    <AlertDialogTrigger
                                        render={
                                            <Button
                                                variant="destructive-outline"
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
                                    This removes the space for everyone. You can only delete a space that has no
                                    sessions or canvases.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
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
                </div>
            </Field>
        </FieldGroup>
    )
}

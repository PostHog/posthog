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
    FieldGroup,
    FieldLabel,
    FieldTitle,
    Input,
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
import { spaceSceneLogic } from './spaceSceneLogic'

const AUTO_ARCHIVE_DAYS = [1, 3, 7, 14, 30]

export function SpaceSettings({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace } = useValues(spaceSceneLogic({ id }))
    const { updateSpace, deleteSpace } = useActions(spaceSceneLogic({ id }))
    const [name, setName] = useState(space?.name ?? '')

    if (!space) {
        return null
    }
    const defaultSpace = space.system_role !== null
    const autoArchiveDays = space.auto_archive_after_days ?? null
    const autoArchiveOptions = [
        { value: null, label: 'Never' },
        ...[...new Set([...AUTO_ARCHIVE_DAYS, ...(autoArchiveDays ? [autoArchiveDays] : [])])]
            .sort((first, second) => first - second)
            .map((days) => ({ value: days, label: `After ${days} ${days === 1 ? 'day' : 'days'}` })),
    ]
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
                <div>
                    <Select
                        items={autoArchiveOptions}
                        value={autoArchiveDays}
                        onValueChange={(days: number | null) => updateSpace({ auto_archive_after_days: days })}
                        disabled={savingSpace}
                    >
                        <SelectTrigger id="space-auto-archive" data-attr="today-space-settings-auto-archive">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {autoArchiveOptions.map((option) => (
                                <SelectItem key={option.label} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <FieldDescription>
                    Sessions with no activity for this long move to the archive. In shared spaces, only project admins
                    can change this.
                </FieldDescription>
            </Field>
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

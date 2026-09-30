import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

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

    return (
        <div className="flex max-w-160 flex-col gap-6">
            <div className="flex flex-col gap-2">
                <LemonLabel htmlFor="space-name">Name</LemonLabel>
                <div className="flex flex-wrap gap-2">
                    <LemonInput
                        id="space-name"
                        className="min-w-60 flex-1"
                        value={defaultSpace ? spaceLabel(space) : name}
                        onChange={setName}
                        disabledReason={defaultSpace ? 'Default spaces can’t be renamed' : undefined}
                        data-attr="today-space-settings-name"
                    />
                    <LemonButton
                        type="secondary"
                        loading={savingSpace}
                        disabledReason={
                            defaultSpace
                                ? 'Default spaces can’t be renamed'
                                : !trimmedName
                                  ? 'Enter a name'
                                  : trimmedName === space.name
                                    ? 'Change the name first'
                                    : undefined
                        }
                        onClick={() => updateSpace({ name: trimmedName })}
                        data-attr="today-space-settings-rename"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <LemonLabel info="Sessions with no activity for this long move to the archive. In shared spaces, only project admins can change this.">
                    Auto-archive sessions
                </LemonLabel>
                <LemonSelect
                    className="self-start"
                    value={autoArchiveDays}
                    options={autoArchiveOptions}
                    onChange={(days) => updateSpace({ auto_archive_after_days: days })}
                    disabledReason={savingSpace ? 'Saving your last change' : undefined}
                    data-attr="today-space-settings-auto-archive"
                />
            </div>
            <div className="flex flex-col gap-2">
                <LemonLabel>Delete space</LemonLabel>
                <LemonButton
                    className="self-start"
                    type="secondary"
                    status="danger"
                    disabledReason={
                        defaultSpace
                            ? 'Default spaces can’t be deleted'
                            : savingSpace
                              ? 'Saving your last change'
                              : undefined
                    }
                    onClick={() =>
                        LemonDialog.open({
                            title: `Delete ${spaceLabel(space)}?`,
                            description:
                                'This removes the space for everyone. You can only delete a space that has no sessions or canvases.',
                            primaryButton: {
                                children: 'Delete',
                                status: 'danger',
                                onClick: deleteSpace,
                                'data-attr': 'today-space-settings-delete-confirm',
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
                    data-attr="today-space-settings-delete"
                >
                    Delete space
                </LemonButton>
            </div>
        </div>
    )
}

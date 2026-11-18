import { useState } from 'react'

import { IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldGroup,
    FieldLabel,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Skeleton,
    Slider,
    Text,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType, ExperimentHoldoutType } from '~/types'

import { QuillConfirmDialog } from 'products/experiments/frontend/components/QuillConfirmDialog'

import {
    DELETE_HOLDOUT_TITLE,
    HOLDOUTS_EMPTY,
    HOLDOUTS_INTRO,
    HOLDOUT_NAME_PLACEHOLDER,
    HOLDOUT_ROLLOUT_HELP,
    useHoldoutsScene,
} from './holdoutsSceneModel'

function InfoItem({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="info">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

export function QuillExperimentsHoldoutsScene(): JSX.Element {
    const {
        holdouts,
        holdoutsLoading,
        holdout,
        setHoldout,
        isModalOpen,
        editingHoldout,
        openEditModal,
        openCreateModal,
        closeModal,
        save,
        saveDisabledReason,
        rolloutPercentage,
        setRolloutPercentage,
        deleteHoldout,
    } = useHoldoutsScene()
    const [pendingDelete, setPendingDelete] = useState<ExperimentHoldoutType | null>(null)

    const columns: DataTableProps<ExperimentHoldoutType, unknown>['columns'] = [
        {
            id: 'name',
            header: 'Name',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <Text size="xs" weight="semibold" render={<span />}>
                    {original.name}
                </Text>
            ),
        },
        {
            id: 'description',
            header: 'Description',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => (
                <Text size="xs" variant="muted" render={<span />}>
                    {original.description}
                </Text>
            ),
        },
        {
            id: 'rollout',
            header: 'Rollout percentage',
            enableSorting: false,
            cell: ({ row: { original } }) => `${original.filters?.[0]?.rollout_percentage || 0} %`,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <span className="flex justify-end gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExperimentHoldout}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={original.user_access_level}
                    >
                        <Button
                            size="icon-xs"
                            aria-label={`Edit ${original.name}`}
                            tooltip="Edit holdout"
                            onClick={() => openEditModal(original)}
                        >
                            <IconPencil />
                        </Button>
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExperimentHoldout}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={original.user_access_level}
                    >
                        <Button
                            size="icon-xs"
                            variant="destructive"
                            aria-label={`Delete ${original.name}`}
                            tooltip="Delete holdout"
                            onClick={() => setPendingDelete(original)}
                        >
                            <IconTrash />
                        </Button>
                    </AccessControlAction>
                </span>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4" data-attr="experiments-holdouts">
            <InfoItem>{HOLDOUTS_INTRO}</InfoItem>
            <div className="flex justify-end">
                <Button variant="primary" onClick={openCreateModal} data-attr="add-holdout">
                    <IconPlus />
                    New holdout
                </Button>
            </div>
            <Card size="sm" flush className="pt-0">
                {holdoutsLoading && holdouts.length === 0 ? (
                    <Skeleton className="m-3 h-24" />
                ) : (
                    <DataTable
                        columns={columns}
                        data={holdouts}
                        fullWidth
                        size="sm"
                        getRowId={(row) => String(row.id)}
                        empty={
                            <Text size="xs" variant="muted">
                                {HOLDOUTS_EMPTY}
                            </Text>
                        }
                    />
                )}
            </Card>

            <Dialog open={isModalOpen} onOpenChange={(open: boolean) => !open && closeModal()}>
                <DialogContent data-attr="experiments-holdout-modal">
                    <DialogHeader>
                        <DialogTitle>{editingHoldout ? 'Edit holdout' : 'Add holdout'}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <FieldGroup>
                            <Field>
                                <FieldLabel htmlFor="holdout-name">Name</FieldLabel>
                                <Input
                                    id="holdout-name"
                                    value={holdout.name}
                                    placeholder={HOLDOUT_NAME_PLACEHOLDER}
                                    onChange={(event) => setHoldout({ name: event.target.value })}
                                />
                            </Field>
                            <Field>
                                <FieldLabel htmlFor="holdout-description">Description</FieldLabel>
                                <Input
                                    id="holdout-description"
                                    value={holdout.description || ''}
                                    onChange={(event) => setHoldout({ description: event.target.value })}
                                />
                            </Field>
                            <InfoItem>{HOLDOUT_ROLLOUT_HELP}</InfoItem>
                            <Field>
                                <FieldLabel htmlFor="holdout-rollout">Roll out to</FieldLabel>
                                <span className="flex items-center gap-3">
                                    <Slider
                                        className="flex-1"
                                        value={rolloutPercentage}
                                        min={0}
                                        max={100}
                                        step={1}
                                        aria-label="Holdout rollout percentage"
                                        onValueChange={(next) =>
                                            setRolloutPercentage(Array.isArray(next) ? next[0] : next)
                                        }
                                    />
                                    <InputGroup className="w-28">
                                        <InputGroupInput
                                            id="holdout-rollout"
                                            type="number"
                                            min={0}
                                            max={100}
                                            step="any"
                                            value={rolloutPercentage}
                                            onChange={(event) => setRolloutPercentage(Number(event.target.value))}
                                            data-attr="rollout-percentage"
                                        />
                                        <InputGroupAddon align="inline-end">%</InputGroupAddon>
                                    </InputGroup>
                                    <Text size="xs" render={<span className="whitespace-nowrap" />}>
                                        of <b>total users.</b>
                                    </Text>
                                </span>
                            </Field>
                        </FieldGroup>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={closeModal}>
                            Cancel
                        </Button>
                        <Button variant="primary" onClick={save} disabledReason={saveDisabledReason}>
                            {editingHoldout ? 'Update' : 'Save'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <QuillConfirmDialog
                open={!!pendingDelete}
                onOpenChange={(open) => !open && setPendingDelete(null)}
                title={DELETE_HOLDOUT_TITLE}
                description={
                    <>
                        Are you sure you want to delete the holdout <b>"{pendingDelete?.name}"</b>? This action cannot
                        be undone.
                    </>
                }
                confirmLabel="Delete"
                destructive
                onConfirm={() => pendingDelete && deleteHoldout(pendingDelete.id)}
                dataAttr="experiments-holdout-delete-confirm"
            />
        </div>
    )
}

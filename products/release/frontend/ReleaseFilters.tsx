import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    Field,
    FieldGroup,
    FieldLabel,
    FilterClearItem,
    FilterMenuTrigger,
    FilterRadioSubMenu,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Textarea,
} from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseStage, STAGE_LABEL } from './releaseUtils'

const STAGES: ReleaseStage[] = ['planned', 'flag', 'experiment', 'early_access', 'released', 'ended']

type StageOption = ReleaseStage | 'all'
type StepOption = 'all' | 'decision'

export function NewReleaseButton(): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { setNewReleaseOpen } = useActions(releaseLogic)
    return (
        <Button
            variant="primary"
            data-attr="release-new"
            disabled={!canEditReleases}
            title={canEditReleases ? undefined : 'You need editor access to feature flags to create a release.'}
            onClick={() => setNewReleaseOpen(true)}
        >
            <IconPlus />
            New release
        </Button>
    )
}

export function ReleaseFilters(): JSX.Element {
    const { search, stageFilter, decisionOnly, rows, decisionRows } = useValues(releaseLogic)
    const { setSearch, setStageFilter, setDecisionOnly } = useActions(releaseLogic)
    const active = !!stageFilter || decisionOnly

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-64">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    placeholder="Search releases or flags"
                    aria-label="Search releases or flags"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    data-attr="release-search"
                />
            </InputGroup>
            <DropdownMenu>
                <FilterMenuTrigger active={active} dataAttr="release-filter" />
                <DropdownMenuContent align="start" className="min-w-64">
                    <FilterRadioSubMenu<StageOption>
                        label="Stage"
                        options={[
                            { value: 'all', label: 'All stages', hint: String(rows.length) },
                            ...STAGES.map((stage) => ({
                                value: stage,
                                label: STAGE_LABEL[stage],
                                hint: String(rows.filter((row) => row.stage === stage).length),
                            })),
                        ]}
                        value={stageFilter ?? 'all'}
                        defaultValue="all"
                        onChange={(value) => setStageFilter(value === 'all' ? null : value)}
                        dataAttr="release-stage-filter"
                    />
                    <FilterRadioSubMenu<StepOption>
                        label="Next step"
                        options={[
                            { value: 'all', label: 'Any' },
                            { value: 'decision', label: 'Needs a decision', hint: String(decisionRows.length) },
                        ]}
                        value={decisionOnly ? 'decision' : 'all'}
                        defaultValue="all"
                        onChange={(value) => setDecisionOnly(value === 'decision')}
                        dataAttr="release-filter-decision"
                        optionDataAttr="release-filter-decision-option"
                    />
                    <DropdownMenuSeparator />
                    <FilterClearItem
                        active={active}
                        onClear={() => {
                            setStageFilter(null)
                            setDecisionOnly(false)
                        }}
                        dataAttr="release-filter-clear"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

export function NewReleaseDialog(): JSX.Element {
    const { newReleaseOpen, creatingRelease } = useValues(releaseLogic)
    const { setNewReleaseOpen, createRelease } = useActions(releaseLogic)
    const [name, setName] = useState('')
    const [description, setDescription] = useState('')

    useEffect(() => {
        if (!newReleaseOpen) {
            setName('')
            setDescription('')
        }
    }, [newReleaseOpen])

    return (
        <Dialog open={newReleaseOpen} onOpenChange={(open: boolean) => setNewReleaseOpen(open)}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New release</DialogTitle>
                    <DialogDescription>
                        A release groups the feature flags, experiments and early access features that ship one change.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor="release-new-name">Name</FieldLabel>
                            <Input
                                id="release-new-name"
                                autoFocus
                                placeholder="Billing alerts"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                data-attr="release-new-name"
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor="release-new-description">Description</FieldLabel>
                            <Textarea
                                id="release-new-description"
                                placeholder="What changes for the user?"
                                value={description}
                                onChange={(event) => setDescription(event.target.value)}
                                data-attr="release-new-description"
                            />
                        </Field>
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setNewReleaseOpen(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={creatingRelease}
                        disabledReason={!name.trim() ? 'Give the release a name' : undefined}
                        data-attr="release-new-create"
                        onClick={() => createRelease(name.trim(), description.trim())}
                    >
                        Create release
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

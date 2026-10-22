import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconBox, IconCheck, IconChevronDown, IconCloud, IconPlus, IconStar, IconStarFilled } from '@posthog/icons'
import {
    Button,
    cn,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemMenuItem,
    ItemTitle,
    MenuLabel,
    Spinner,
} from '@posthog/quill-primitives'

import { CloudEnvironmentModal } from 'scenes/settings/environment/CloudEnvironmentModal'
import { cloudEnvironmentsLogic } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import type { SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { cloudTargetKey, unattachedImages } from '../../../utils/cloudTargets'
import { composerSandboxEnvironmentsLogic } from '../composerSandboxEnvironmentsLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

interface CloudTargetOption {
    key: string
    name: string
    description: string
}

function environmentDescription(environment: SandboxEnvironmentDTOApi): string {
    if (environment.network_access_level === 'full') {
        return 'Full network access'
    }
    if (environment.network_access_level === 'trusted') {
        return 'Trusted sources only'
    }
    const count = environment.allowed_domains?.length ?? 0
    return `${count} allowed domain${count === 1 ? '' : 's'}`
}

interface OptionRowProps {
    icon: JSX.Element
    title: string
    description: string
    selected: boolean
    onSelect: () => void
    onToggleFavorite?: () => void
    actions?: JSX.Element
}

function OptionRow({
    icon,
    title,
    description,
    selected,
    onSelect,
    onToggleFavorite,
    actions,
}: OptionRowProps): JSX.Element {
    return (
        <DropdownMenuItem
            aria-current={selected ? 'true' : undefined}
            aria-keyshortcuts={onToggleFavorite ? 'S' : undefined}
            onClick={onSelect}
            onKeyDown={(event) => {
                if (onToggleFavorite && event.key.toLowerCase() === 's' && !event.metaKey && !event.ctrlKey) {
                    event.preventDefault()
                    event.stopPropagation()
                    onToggleFavorite()
                }
            }}
            render={
                <ItemMenuItem size="xs" className="w-full flex-nowrap" render={<div />}>
                    <ItemMedia variant="icon" className="mt-2 ml-2">
                        {icon}
                    </ItemMedia>
                    <ItemContent variant="menuItem" className="min-w-0">
                        <ItemTitle className="w-full min-w-0" title={title}>
                            <span className="block truncate">{title}</span>
                        </ItemTitle>
                        <ItemDescription className="leading-none">{description}</ItemDescription>
                    </ItemContent>
                    <ItemActions className="mr-1.5 ml-auto self-center">
                        {actions}
                        <IconCheck aria-hidden="true" className={cn('shrink-0', !selected && 'opacity-0')} />
                    </ItemActions>
                </ItemMenuItem>
            }
        />
    )
}

export function TaskComposerEnvironmentSelect(): JSX.Element {
    const panelId = useMountedLogic(taskTrackerSceneLogic).props.panelId
    const composerEnvironments = composerSandboxEnvironmentsLogic({ panelId })
    const { createEnvironment, retryCloudTargets } = useActions(composerEnvironments)
    const { imagesFailed, imagesLoading, configFailed, awaitingCreatedEnvironment } = useValues(composerEnvironments)
    const { environmentsLoading, environmentsFailed, draft } = useValues(cloudEnvironmentsLogic)
    const {
        selectedCloudTarget,
        favoriteCloudTarget,
        sandboxEnvironments,
        customImages,
        isSubmittingTask,
        defaultCloudTargetSaving,
        taskDefaults,
    } = useValues(taskTrackerSceneLogic)
    const { pickCloudTarget, toggleFavoriteCloudTarget } = useActions(taskTrackerSceneLogic)
    const [open, setOpen] = useState(false)

    const favoriteSaving = defaultCloudTargetSaving || !taskDefaults
    const favoriteFirst = (options: CloudTargetOption[]): CloudTargetOption[] => [
        ...options.filter((option) => option.key === favoriteCloudTarget),
        ...options.filter((option) => option.key !== favoriteCloudTarget),
    ]
    const environmentOptions = favoriteFirst(
        (sandboxEnvironments ?? []).map((environment) => ({
            key: cloudTargetKey('environment', environment.id),
            name: environment.name,
            description: environmentDescription(environment),
        }))
    )
    const imageOptions = favoriteFirst(
        unattachedImages(customImages, sandboxEnvironments, [selectedCloudTarget, favoriteCloudTarget]).map(
            (image) => ({
                key: cloudTargetKey('image', image.id),
                name: image.name,
                description: `v${image.version}, full network access`,
            })
        )
    )
    const selectedName = [...environmentOptions, ...imageOptions].find(
        (option) => option.key === selectedCloudTarget
    )?.name
    const triggerLabel = selectedName ?? 'Default'

    const pick = (cloudTarget: string | null): void => {
        setOpen(false)
        pickCloudTarget(cloudTarget)
    }
    const create = (): void => {
        setOpen(false)
        createEnvironment()
    }
    const renderOption =
        (icon: JSX.Element) =>
        (option: CloudTargetOption): JSX.Element => {
            const isFavorite = option.key === favoriteCloudTarget
            return (
                <OptionRow
                    key={option.key}
                    icon={icon}
                    title={option.name}
                    description={option.description}
                    selected={option.key === selectedCloudTarget}
                    onSelect={() => pick(option.key)}
                    onToggleFavorite={favoriteSaving ? undefined : () => toggleFavoriteCloudTarget(option.key)}
                    actions={
                        <Button
                            type="button"
                            size="icon-xs"
                            variant="default"
                            tabIndex={-1}
                            disabled={favoriteSaving}
                            aria-label={
                                isFavorite ? `Stop using ${option.name} by default` : `Use ${option.name} by default`
                            }
                            aria-pressed={isFavorite}
                            title={`${isFavorite ? 'Stop using' : 'Use'} ${option.name} by default (S)`}
                            onPointerDown={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                            }}
                            onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                toggleFavoriteCloudTarget(option.key)
                            }}
                            className={cn(
                                isFavorite
                                    ? 'text-foreground'
                                    : 'text-muted-foreground opacity-0 group-hover/dropdown-menu-item:opacity-100'
                            )}
                        >
                            {isFavorite ? <IconStarFilled /> : <IconStar />}
                        </Button>
                    }
                />
            )
        }

    return (
        <>
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger
                    render={
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isSubmittingTask}
                            aria-label="Environment"
                            title={triggerLabel}
                            data-attr="task-composer-environment"
                        >
                            <IconCloud className="shrink-0 text-muted-foreground" />
                            <span className="max-w-40 truncate">{triggerLabel}</span>
                            <IconChevronDown className="shrink-0 text-muted-foreground" />
                        </Button>
                    }
                />
                <DropdownMenuContent
                    align="start"
                    side="bottom"
                    sideOffset={6}
                    className="w-auto max-w-[360px] min-w-[280px]"
                >
                    <div className="flex items-center justify-between px-2 py-1">
                        <MenuLabel className="p-0">Cloud environments</MenuLabel>
                        <Button
                            type="button"
                            size="icon-xs"
                            variant="default"
                            aria-label="Create cloud environment"
                            onClick={create}
                        >
                            <IconPlus />
                        </Button>
                    </div>
                    <DropdownMenuGroup className="max-h-[min(20rem,calc(var(--available-height,20rem)-3rem))] overflow-y-auto">
                        <OptionRow
                            icon={<IconCloud />}
                            title="Default"
                            description="Full network access"
                            selected={selectedCloudTarget === null}
                            onSelect={() => pick(null)}
                        />
                        {environmentOptions.map(renderOption(<IconCloud />))}
                        {imageOptions.length > 0 && (
                            <>
                                <div className="px-2 py-1">
                                    <MenuLabel className="p-0">Images</MenuLabel>
                                </div>
                                {imageOptions.map(renderOption(<IconBox />))}
                            </>
                        )}
                    </DropdownMenuGroup>
                    {(environmentsLoading && !sandboxEnvironments) || (imagesLoading && !customImages) ? (
                        <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                            <Spinner className="size-3" />
                            Loading environments…
                        </div>
                    ) : environmentsFailed || imagesFailed || configFailed ? (
                        <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground">
                            <span>Couldn't load all your environments.</span>
                            <Button type="button" size="xs" variant="outline" onClick={retryCloudTargets}>
                                Retry
                            </Button>
                        </div>
                    ) : sandboxEnvironments && environmentOptions.length + imageOptions.length === 0 ? (
                        <OptionRow
                            icon={<IconPlus />}
                            title="Create a custom environment"
                            description="Set which hosts the sandbox can reach"
                            selected={false}
                            onSelect={create}
                        />
                    ) : null}
                </DropdownMenuContent>
            </DropdownMenu>
            {draft && awaitingCreatedEnvironment && <CloudEnvironmentModal />}
        </>
    )
}

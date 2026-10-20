import { useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconChevronDown, IconCloud, IconBox, IconPlus, IconStar, IconStarFilled } from '@posthog/icons'
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

import type { SandboxCustomImageDTOApi, SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { cloudTargetKey, standaloneReadyImages } from '../../utils/cloudTargets'

export interface QuillCloudEnvironmentSelectProps {
    value: string | null
    favorite: string | null
    environments: SandboxEnvironmentDTOApi[] | null
    images: SandboxCustomImageDTOApi[] | null
    onChange: (cloudTarget: string | null) => void
    onToggleFavorite: (cloudTarget: string) => void
    onCreate: () => void
    onRetry: () => void
    loading: boolean
    failed: boolean
    favoriteSaving: boolean
    ownsEnvironmentForm: boolean
    disabled?: boolean
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

function SelectedCheck({ selected }: { selected: boolean }): JSX.Element {
    return <IconCheck aria-hidden="true" className={cn('shrink-0', !selected && 'opacity-0')} />
}

interface CloudTargetOption {
    key: string
    name: string
    description: string
    image: boolean
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
                        <SelectedCheck selected={selected} />
                    </ItemActions>
                </ItemMenuItem>
            }
        />
    )
}

export function QuillCloudEnvironmentSelect({
    value,
    favorite,
    environments,
    images,
    onChange,
    onToggleFavorite,
    onCreate,
    onRetry,
    loading,
    failed,
    favoriteSaving,
    ownsEnvironmentForm,
    disabled,
}: QuillCloudEnvironmentSelectProps): JSX.Element {
    const { draft } = useValues(cloudEnvironmentsLogic)
    const [open, setOpen] = useState(false)

    const options: CloudTargetOption[] = [
        ...(environments ?? []).map((environment) => ({
            key: cloudTargetKey('environment', environment.id),
            name: environment.name,
            description: environmentDescription(environment),
            image: false,
        })),
        ...standaloneReadyImages(images, environments).map((image) => ({
            key: cloudTargetKey('image', image.id),
            name: image.name,
            description: `v${image.version}, full network access`,
            image: true,
        })),
    ]
    const favoriteOption = options.find((option) => option.key === favorite)
    const sorted = favoriteOption ? [favoriteOption, ...options.filter((option) => option !== favoriteOption)] : options
    const environmentOptions = sorted.filter((option) => !option.image)
    const imageOptions = sorted.filter((option) => option.image)
    const selectedName = value ? options.find((option) => option.key === value)?.name : null
    const triggerLabel = ['Cloud', selectedName].filter(Boolean).join(' · ')

    const pick = (cloudTarget: string | null): void => {
        setOpen(false)
        onChange(cloudTarget)
    }
    const renderOption = (option: CloudTargetOption): JSX.Element => {
        const isFavorite = option.key === favorite
        return (
            <OptionRow
                key={option.key}
                icon={option.image ? <IconBox /> : <IconCloud />}
                title={option.name}
                description={option.description}
                selected={option.key === value}
                onSelect={() => pick(option.key)}
                onToggleFavorite={favoriteSaving ? undefined : () => onToggleFavorite(option.key)}
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
                            onToggleFavorite(option.key)
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
    const create = (): void => {
        setOpen(false)
        onCreate()
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
                            disabled={disabled}
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
                            selected={value === null}
                            onSelect={() => pick(null)}
                        />
                        {environmentOptions.map(renderOption)}
                        {imageOptions.length > 0 && (
                            <>
                                <div className="px-2 py-1">
                                    <MenuLabel className="p-0">Images</MenuLabel>
                                </div>
                                {imageOptions.map(renderOption)}
                            </>
                        )}
                    </DropdownMenuGroup>
                    {loading ? (
                        <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                            <Spinner className="size-3" />
                            Loading environments…
                        </div>
                    ) : failed ? (
                        <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground">
                            <span>Couldn't load all your environments.</span>
                            <Button type="button" size="xs" variant="outline" onClick={onRetry}>
                                Retry
                            </Button>
                        </div>
                    ) : environments && options.length === 0 ? (
                        <DropdownMenuItem
                            onClick={create}
                            render={
                                <ItemMenuItem size="xs" className="w-full flex-nowrap" render={<div />}>
                                    <ItemMedia variant="icon" className="mt-2 ml-2">
                                        <IconPlus />
                                    </ItemMedia>
                                    <ItemContent variant="menuItem" className="min-w-0">
                                        <ItemTitle>Create a custom environment</ItemTitle>
                                        <ItemDescription className="leading-none">
                                            Set which hosts the sandbox can reach
                                        </ItemDescription>
                                    </ItemContent>
                                </ItemMenuItem>
                            }
                        />
                    ) : null}
                </DropdownMenuContent>
            </DropdownMenu>
            {draft && ownsEnvironmentForm && <CloudEnvironmentModal />}
        </>
    )
}

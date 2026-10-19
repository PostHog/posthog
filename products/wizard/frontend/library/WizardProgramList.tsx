import { IconSearch } from '@posthog/icons'
import {
    Button,
    Card,
    CardGroup,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill-primitives'

import type { WizardProgramApi } from '../generated/api.schemas'
import { WIZARD_LOCAL_RUNS_VISIBLE } from '../wizardRunDisplay'

export function WizardProgramList({
    programs,
    selectedProgram,
    search,
    loading,
    failed,
    onSearch,
    onSelect,
}: {
    programs: WizardProgramApi[]
    selectedProgram: WizardProgramApi | null
    search: string
    loading: boolean
    failed: boolean
    onSearch: (search: string) => void
    onSelect: (program: WizardProgramApi) => void
}): JSX.Element {
    return (
        <div className="flex h-1/2 min-h-0 w-full flex-col gap-3 border-b p-4 @3xl:h-full @3xl:w-[340px] @3xl:shrink-0 @3xl:border-b-0 @3xl:border-r">
            <InputGroup>
                <InputGroupInput
                    value={search}
                    onChange={(event) => onSearch(event.target.value)}
                    placeholder="Search programs"
                    disabled={loading}
                />
                <InputGroupAddon align="inline-start">
                    <IconSearch />
                </InputGroupAddon>
            </InputGroup>

            <div className="min-h-0 flex-1 overflow-y-auto">
                {loading ? (
                    <div className="flex flex-col gap-2">
                        {Array.from({ length: 7 }).map((_, index) => (
                            <Skeleton key={index} className="h-14 w-full" />
                        ))}
                    </div>
                ) : failed ? (
                    <Empty className="py-8">
                        <EmptyHeader>
                            <EmptyTitle>Couldn’t load the Wizard Library</EmptyTitle>
                            <EmptyDescription>Close and reopen it to try again.</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : programs.length === 0 ? (
                    search.trim() ? (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyTitle>No matching programs</EmptyTitle>
                                <EmptyDescription>
                                    Try a different search, or clear it to see all programs.
                                </EmptyDescription>
                            </EmptyHeader>
                            <Button variant="outline" size="sm" onClick={() => onSearch('')}>
                                Clear search
                            </Button>
                        </Empty>
                    ) : (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyTitle>No programs are available</EmptyTitle>
                                <EmptyDescription>
                                    Refresh the page, or contact support if you expected to see a program.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    )
                ) : (
                    <CardGroup>
                        {programs.map((program) => {
                            const selected = selectedProgram?.id === program.id
                            return (
                                <Card key={program.id} size="sm" className="p-0">
                                    <button
                                        type="button"
                                        onClick={() => onSelect(program)}
                                        aria-pressed={selected}
                                        className={cn(
                                            'flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30',
                                            selected && 'bg-fill-selected hover:bg-fill-selected'
                                        )}
                                    >
                                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                                            <Text
                                                size="sm"
                                                weight="medium"
                                                render={<span />}
                                                className="block truncate"
                                            >
                                                {program.name}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span />} className="block">
                                                {program.description}
                                            </Text>
                                        </span>
                                        <Text
                                            size="xs"
                                            variant="muted"
                                            render={<span />}
                                            className="shrink-0 whitespace-nowrap"
                                        >
                                            {program.supported_environments
                                                .filter(
                                                    (environment) =>
                                                        WIZARD_LOCAL_RUNS_VISIBLE || environment === 'cloud'
                                                )
                                                .map((environment) => (environment === 'cloud' ? 'Cloud' : 'Local'))
                                                .join(' · ')}
                                        </Text>
                                    </button>
                                </Card>
                            )
                        })}
                    </CardGroup>
                )}
            </div>
        </div>
    )
}

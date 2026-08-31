import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import type { WizardProgramApi } from '../generated/api.schemas'

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
        <div className="flex h-full min-h-0 w-full flex-col gap-3 border-b pb-4 lg:w-90 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-4">
            <LemonInput
                value={search}
                onChange={onSearch}
                prefix={<IconSearch />}
                placeholder="Search programs"
                fullWidth
                disabled={loading}
            />

            <div className="min-h-0 flex-1 overflow-y-auto">
                {loading ? (
                    <div className="space-y-3 p-2">
                        <LemonSkeleton repeat={7} className="h-14 w-full" />
                    </div>
                ) : failed ? (
                    <div className="p-4 text-center text-sm text-muted">
                        Couldn’t load the Wizard Library. Close and reopen it to try again.
                    </div>
                ) : programs.length === 0 ? (
                    <div className="p-6 text-center">
                        <div className="font-semibold">No programs are available</div>
                        <p className="mt-1 text-sm text-muted">
                            Refresh the page, or contact support if you expected to see a program.
                        </p>
                    </div>
                ) : (
                    <div className="flex flex-col">
                        {programs.map((program) => (
                            <LemonButton
                                key={program.id}
                                type="tertiary"
                                fullWidth
                                className={`h-auto justify-start !rounded-none border-l-2 px-3 py-2 text-left ${
                                    selectedProgram?.id === program.id
                                        ? 'border-l-accent bg-fill-highlight-100'
                                        : 'border-l-transparent'
                                }`}
                                onClick={() => onSelect(program)}
                            >
                                <div className="w-full min-w-0">
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0 font-semibold">{program.name}</div>
                                        <span className="shrink-0 whitespace-nowrap text-xs font-normal text-muted">
                                            {program.supported_environments
                                                .map((environment) => (environment === 'cloud' ? 'Cloud' : 'Local'))
                                                .join(' · ')}
                                        </span>
                                    </div>
                                    <div className="line-clamp-2 text-xs font-normal text-muted">
                                        {program.description}
                                    </div>
                                </div>
                            </LemonButton>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

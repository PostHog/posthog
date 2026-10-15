import type {
    AutomaticFlashForEnumApi,
    AutomaticReviewDecisionApi,
    AutomaticReviewReasonEnumApi,
    DefaultReviewModeEnumApi,
    ReviewInstallationApi,
    ReviewProjectRefApi,
    ReviewRepositoryOverviewEntryApi,
    ReviewRepositoryPersonKindEnumApi,
    ReviewUserRepositoryChoiceModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

export interface ChoiceOption<T extends string> {
    value: T
    label: string
}

export const FLASH_FOR_OPTIONS: ChoiceOption<AutomaticFlashForEnumApi>[] = [
    { value: 'everyone', label: 'Automatic review for everyone' },
    { value: 'listed', label: 'Automatic review for these people' },
    { value: 'off', label: 'Only people who opt in' },
]

export function flashForLabel(flashFor: AutomaticFlashForEnumApi): string {
    return FLASH_FOR_OPTIONS.find((option) => option.value === flashFor)?.label ?? flashFor
}

export const DEFAULT_REVIEW_MODE_OPTIONS: ChoiceOption<DefaultReviewModeEnumApi>[] = [
    { value: 'follow', label: 'Let each repository decide' },
    { value: 'flash', label: 'On everywhere' },
    { value: 'off', label: 'Off everywhere' },
]

export function defaultReviewModeLabel(mode: DefaultReviewModeEnumApi): string {
    return DEFAULT_REVIEW_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode
}

/** The people list a rule reads: the except list for "everyone", the people list for "listed", none for "off". */
export function peopleKindFor(flashFor: AutomaticFlashForEnumApi): ReviewRepositoryPersonKindEnumApi | null {
    if (flashFor === 'everyone') {
        return 'excepted'
    }
    return flashFor === 'listed' ? 'listed' : null
}

const SOURCES: Record<AutomaticReviewReasonEnumApi, string> = {
    own_repository_choice: 'your choice',
    own_default: 'your default',
    repository_everyone: 'repository exception',
    repository_excepted: 'repository exception',
    repository_listed: 'repository exception',
    repository_not_listed: 'repository exception',
    repository_opt_in: 'repository exception',
    project_everyone: 'project',
    project_excepted: 'project',
    project_listed: 'project',
    project_not_listed: 'project',
    project_opt_in: 'project',
    bot_reviewed: 'project',
    bot_skipped: 'project',
    not_in_project: 'not part of this project',
}

/** Where a result comes from, in the words the "My pull requests" pane uses. */
export function describeSource(decision: AutomaticReviewDecisionApi): string {
    return SOURCES[decision.reason]
}

export function describeResult(decision: AutomaticReviewDecisionApi): string {
    return decision.flash ? 'Automatic review' : 'No automatic review'
}

/** The note under a repository's own choice, or null when the select already says enough. */
export function myChoiceNote(entry: ReviewRepositoryOverviewEntryApi): string | null {
    const inherited = entry.inherited_result
    if (entry.my_choice !== null) {
        return `Your choice. Without it: ${describeResult(inherited).toLowerCase()} (${describeSource(inherited)})`
    }
    // Rows on the project rule get no note: the notice under My default already covers them.
    const repositoryResult = entry.repository_result
    if (inherited.reason === 'own_default' && entry.exception !== null && repositoryResult.flash !== inherited.flash) {
        return `The repository alone gives: ${describeResult(repositoryResult).toLowerCase()}`
    }
    return null
}

/** The notice for a default that overrides every repository, or null while the default lets each one decide. */
export function myDefaultNotice(mode: DefaultReviewModeEnumApi, choicesUnlikeDefault: number | null): string | null {
    if (mode === 'follow') {
        return null
    }
    const notice = `Your default, ${defaultReviewModeLabel(mode)}, applies to your PRs in every repository`
    if (!choicesUnlikeDefault) {
        return `${notice}.`
    }
    return `${notice}, except ${choicesUnlikeDefault} where you picked something else.`
}

export type MyChoiceValue = ReviewUserRepositoryChoiceModeEnumApi | 'follow'

export function myChoiceValue(entry: ReviewRepositoryOverviewEntryApi): MyChoiceValue {
    return entry.my_choice ?? 'follow'
}

const CHOICE_LABELS: Record<ReviewUserRepositoryChoiceModeEnumApi, string> = {
    flash: 'On for me',
    off: 'Off for me',
}

/**
 * Offering the inherited value as its own option would look like a pin, but the API stores only what
 * differs, so the pick would vanish. A choice saved before the inherited value changed is the exception.
 */
export function myChoiceOptions(entry: ReviewRepositoryOverviewEntryApi): ChoiceOption<MyChoiceValue>[] {
    const inherited = entry.inherited_result
    const opposite: ReviewUserRepositoryChoiceModeEnumApi = inherited.flash ? 'off' : 'flash'
    const options: ChoiceOption<MyChoiceValue>[] = [
        { value: 'follow', label: `${describeResult(inherited)} (${describeSource(inherited)})` },
        { value: opposite, label: CHOICE_LABELS[opposite] },
    ]
    if (entry.my_choice !== null && entry.my_choice !== opposite) {
        options.push({ value: entry.my_choice, label: CHOICE_LABELS[entry.my_choice] })
    }
    return options
}

export function projectName(project: ReviewProjectRefApi | null): string {
    return project?.name ? `the ${project.name} project` : 'a project in another organization'
}

function sameProject(left: ReviewProjectRefApi, right: ReviewProjectRefApi): boolean {
    return left.id === right.id && left.name === right.name
}

/**
 * A repository another project reviews only through its "all repositories" claim can still be
 * included here, which takes it from that project. One that another project selected cannot.
 */
export function canTakeFromOtherProject(
    entry: ReviewRepositoryOverviewEntryApi,
    installation: ReviewInstallationApi | null
): boolean {
    const takenBy = installation?.all_taken_by_project ?? null
    return (
        entry.owner === 'other_project' &&
        takenBy !== null &&
        entry.owner_project !== null &&
        sameProject(entry.owner_project, takenBy)
    )
}

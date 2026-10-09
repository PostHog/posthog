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
    { value: 'everyone', label: 'Automatic Flash for everyone' },
    { value: 'listed', label: 'Automatic Flash for these people' },
    { value: 'off', label: 'Automatic Flash: opt-in only' },
]

export function flashForLabel(flashFor: AutomaticFlashForEnumApi): string {
    return FLASH_FOR_OPTIONS.find((option) => option.value === flashFor)?.label ?? flashFor
}

export const DEFAULT_REVIEW_MODE_OPTIONS: ChoiceOption<DefaultReviewModeEnumApi>[] = [
    { value: 'follow', label: 'Follow each repository' },
    { value: 'flash', label: 'Flash everywhere' },
    { value: 'off', label: 'Off everywhere' },
]

/** The people list a rule reads: the except list for "everyone", the people list for "listed", none for "off". */
export function peopleKindFor(flashFor: AutomaticFlashForEnumApi): ReviewRepositoryPersonKindEnumApi | null {
    if (flashFor === 'everyone') {
        return 'excepted'
    }
    return flashFor === 'listed' ? 'listed' : null
}

const REASONS: Record<AutomaticReviewReasonEnumApi, string> = {
    own_repository_choice: 'Your choice for this repository',
    own_default: 'Your default',
    repository_everyone: "This repository's exception: everyone",
    repository_excepted: "This repository's exception: you are on the except list",
    repository_listed: "This repository's exception: you are on the list",
    repository_not_listed: "This repository's exception: you are not on the list",
    repository_opt_in: "This repository's exception: opt-in only",
    project_everyone: 'Project settings: everyone',
    project_excepted: 'Project settings: you are on the except list',
    project_listed: 'Project settings: you are on the list',
    project_not_listed: 'Project settings: you are not on the list',
    project_opt_in: 'Project settings: opt-in only',
    bot_reviewed: 'The project reviews bot pull requests',
    bot_skipped: 'The project does not review bot pull requests',
    not_in_project: 'Not part of this project',
}

export function describeReason(decision: AutomaticReviewDecisionApi): string {
    return REASONS[decision.reason]
}

export function describeResult(decision: AutomaticReviewDecisionApi): string {
    return decision.flash ? 'Automatic Flash' : 'No automatic Flash'
}

export type MyChoiceValue = ReviewUserRepositoryChoiceModeEnumApi | 'follow'

export function myChoiceValue(entry: ReviewRepositoryOverviewEntryApi): MyChoiceValue {
    return entry.my_choice ?? 'follow'
}

const CHOICE_LABELS: Record<ReviewUserRepositoryChoiceModeEnumApi, string> = {
    flash: 'Flash for me',
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
        { value: 'follow', label: `${describeResult(inherited)} (follow)` },
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

import { pluralize } from 'lib/utils/strings'

import type {
    AutomaticFlashForEnumApi,
    AutomaticReviewDecisionApi,
    AutomaticReviewReasonEnumApi,
    DefaultReviewModeEnumApi,
    ReviewInstallationApi,
    ReviewProjectRefApi,
    ReviewProjectSettingsApi,
    ReviewRepositoryOverviewEntryApi,
    ReviewRepositoryPersonKindEnumApi,
    ReviewUserRepositoryChoiceModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

export interface ChoiceOption<T extends string> {
    value: T
    label: string
}

export const FLASH_FOR_OPTIONS: ChoiceOption<AutomaticFlashForEnumApi>[] = [
    { value: 'everyone', label: 'Everyone' },
    { value: 'listed', label: 'Selected people' },
    { value: 'off', label: 'People who opt in' },
]

export const DEFAULT_REVIEW_MODE_OPTIONS: ChoiceOption<DefaultReviewModeEnumApi>[] = [
    { value: 'follow', label: 'Let each repository decide' },
    { value: 'flash', label: 'On everywhere' },
    { value: 'off', label: 'Off everywhere' },
]

/** The people list a rule reads: the except list for "everyone", the people list for "listed", none for "off". */
export function peopleKindFor(flashFor: AutomaticFlashForEnumApi): ReviewRepositoryPersonKindEnumApi | null {
    if (flashFor === 'everyone') {
        return 'excepted'
    }
    return flashFor === 'listed' ? 'listed' : null
}

/** The project rule in one sentence, for the tab where its controls are not shown. */
export function projectRuleSummary(project: ReviewProjectSettingsApi): string {
    const flashFor = project.flash_for ?? 'off'
    const kind = peopleKindFor(flashFor)
    const count = project.people.filter((person) => person.kind === kind).length
    if (flashFor === 'everyone') {
        return count
            ? `Project rule: everyone, except ${pluralize(count, 'person', 'people')}.`
            : 'Project rule: everyone.'
    }
    if (flashFor === 'listed') {
        return `Project rule: ${pluralize(count, 'selected person', 'selected people')}.`
    }
    return 'Project rule: people who opt in.'
}

const SOURCES: Record<AutomaticReviewReasonEnumApi, string> = {
    own_repository_choice: 'your choice',
    own_default: 'your default',
    repository_everyone: 'repository exception',
    repository_excepted: 'repository exception',
    repository_listed: 'repository exception',
    repository_not_listed: 'repository exception',
    repository_opt_in: 'repository exception',
    project_everyone: 'project rule',
    project_excepted: 'project rule',
    project_listed: 'project rule',
    project_not_listed: 'project rule',
    project_opt_in: 'project rule',
    bot_reviewed: 'project rule',
    bot_skipped: 'project rule',
    not_in_project: 'not part of this project',
}

/** Where a result comes from, in the words the per-repository list on My preferences uses. */
export function describeSource(decision: AutomaticReviewDecisionApi): string {
    return SOURCES[decision.reason]
}

export function describeResult(decision: AutomaticReviewDecisionApi): string {
    return decision.flash ? 'On' : 'Off'
}

/** The note under a repository's own choice, or null when the select already says enough. */
export function myChoiceNote(entry: ReviewRepositoryOverviewEntryApi): string | null {
    const inherited = entry.inherited_result
    if (entry.my_choice !== null) {
        return `Your choice. Without it: ${describeResult(inherited).toLowerCase()} (${describeSource(inherited)})`
    }
    // Rows on the project rule get no note: the description of the viewer's default already covers them.
    const repositoryResult = entry.repository_result
    if (inherited.reason === 'own_default' && entry.exception !== null && repositoryResult.flash !== inherited.flash) {
        return `Your default. Without it: ${describeResult(repositoryResult).toLowerCase()} (repository exception)`
    }
    return null
}

/** What a default that overrides every repository covers, or null while the default follows the project rules. */
export function myDefaultNotice(mode: DefaultReviewModeEnumApi, choicesUnlikeDefault: number | null): string | null {
    if (mode === 'follow') {
        return null
    }
    const notice = 'This applies to your pull requests in every repository'
    if (!choicesUnlikeDefault) {
        return `${notice}.`
    }
    return `${notice}, except ${choicesUnlikeDefault} where you chose differently.`
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

import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'

import { PANE_LEFT, PANE_RIGHT, PANE_ROW } from './paneClasses'
import { FLASH_FOR_OPTIONS, describeResult, describeSource } from './repositoryChoices'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { FoldSummary, reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { RuleStateIcon } from './RuleStateIcon'

/** "mobile-app, infra and sdk-js", so the row says which repositories it holds. */
function previewNames(summary: FoldSummary): string {
    const names = summary.preview.map((fullName) => fullName.split('/').pop() ?? fullName)
    if (names.length < 2) {
        return names.join('')
    }
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/**
 * One row for every repository that follows the project with no exception and no own choice. Those
 * repositories all get the same result, so one row states it once instead of repeating it per repository.
 */
export function RepositoryFoldRow({ summary }: { summary: FoldSummary }): JSX.Element {
    const { projectSettings } = useValues(reviewHogProjectSettingsLogic)
    const { foldOpen } = useValues(reviewHogRepositoriesLogic)
    const { setFoldOpen } = useActions(reviewHogRepositoriesLogic)
    const flashFor = projectSettings?.flash_for ?? 'off'
    const rule = FLASH_FOR_OPTIONS.find((option) => option.value === flashFor)?.label ?? ''

    return (
        <>
            <button
                type="button"
                onClick={() => setFoldOpen(!foldOpen)}
                aria-expanded={foldOpen}
                className={`flex min-w-0 cursor-pointer items-start gap-1.5 px-4 py-2.5 text-left ${PANE_LEFT} ${PANE_ROW}`}
                data-attr="review-hog-repository-fold"
            >
                <IconChevronRight
                    className={`mt-0.5 shrink-0 text-base transition-transform motion-reduce:transition-none ${foldOpen ? 'rotate-90' : ''}`}
                />
                <span className="flex min-w-0 flex-col">
                    <span className="text-sm font-semibold">
                        {foldOpen ? 'Showing all repositories' : `${summary.count} more repositories`}
                    </span>
                    {!foldOpen && (
                        <span className="truncate text-xs text-secondary">
                            {summary.count > summary.preview.length
                                ? `Like ${previewNames(summary)}`
                                : previewNames(summary)}
                        </span>
                    )}
                </span>
            </button>
            <div className={`flex min-w-0 items-center gap-2 px-4 py-2.5 text-xs ${PANE_LEFT} ${PANE_ROW}`}>
                <RuleStateIcon flashFor={flashFor} />
                <span>
                    <span className="text-secondary">No exception, so the project default applies:</span>{' '}
                    <span>{rule.toLowerCase()}</span>
                </span>
            </div>
            <div className={`flex min-w-0 items-center gap-2 px-4 py-2.5 text-xs ${PANE_RIGHT} ${PANE_ROW}`}>
                {summary.result && (
                    <>
                        <span
                            className={`inline-block size-2 shrink-0 rounded-full ${summary.result.flash ? 'bg-success' : 'bg-border-bold'}`}
                        />
                        <span>
                            <span>{`${describeResult(summary.result)} (${describeSource(summary.result)})`}</span>
                            <span className="text-secondary"> · no choices of yours</span>
                        </span>
                    </>
                )}
            </div>
        </>
    )
}

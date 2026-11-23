import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconGitLab } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Spinner,
    Text,
} from '@posthog/quill-primitives'

import { ComboboxSearchField } from 'lib/integrations/ComboboxSearchChrome'
import { cn } from 'lib/utils/css-classes'

import { gitlabProjectsLogic } from '../../../logics/gitlabProjectsLogic'
import type { GitlabProjectOption } from '../../../utils/gitlabProjects'

export interface GitLabProjectComboboxProps {
    /** Selected project path, or empty when no GitLab project is picked. */
    value: string
    onChange: (option: GitlabProjectOption) => void
    triggerClassName?: string
    contentSide?: 'top' | 'bottom'
    contentClassName?: string
}

/** Picks a gitlab.com project for a task. Projects load only while the picker is open. */
export function GitLabProjectCombobox({
    value,
    onChange,
    triggerClassName,
    contentSide = 'bottom',
    contentClassName,
}: GitLabProjectComboboxProps): JSX.Element {
    const { gitlabProjects, gitlabProjectResultsLoading } = useValues(gitlabProjectsLogic)
    const { openGitlabProjectPicker, loadGitlabProjects, reportGitlabProjectPicked } = useActions(gitlabProjectsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    const projects = gitlabProjects?.projects ?? []
    const loadFailed = !!gitlabProjects?.loadFailed
    const missingScopes = gitlabProjects?.missingScopes ?? []
    // Projects from an earlier open stay listed while a reopen refetches them.
    const loading = gitlabProjectResultsLoading && projects.length === 0

    return (
        <Combobox
            items={projects.map(({ project }) => project)}
            value={value || null}
            onValueChange={(next: string | null) => {
                const option = projects.find(({ project }) => project === next)
                if (option) {
                    reportGitlabProjectPicked()
                    onChange(option)
                }
            }}
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                setOpen(nextOpen)
                if (nextOpen) {
                    openGitlabProjectPicker()
                }
            }}
        >
            <ComboboxTrigger
                render={
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        aria-label="GitLab project"
                        className={triggerClassName}
                        data-attr="task-composer-gitlab-project"
                    >
                        <IconGitLab className="shrink-0" />
                        <span className="min-w-0 truncate">{value || 'GitLab project'}</span>
                    </Button>
                }
            />
            <ComboboxContent
                anchor={triggerRef}
                side={contentSide}
                sideOffset={6}
                className={contentClassName ?? 'min-w-[280px]'}
            >
                <ComboboxSearchField
                    itemsLabel="GitLab projects"
                    loading={gitlabProjectResultsLoading}
                    onRefresh={loadGitlabProjects}
                />
                {missingScopes.length > 0 && (
                    <Text
                        size="xs"
                        variant="muted"
                        className="border-b px-3 py-2"
                        data-attr="task-composer-gitlab-missing-scopes"
                    >
                        {`Tasks need a GitLab token with the ${missingScopes.join(', ')} ${
                            missingScopes.length === 1 ? 'scope' : 'scopes'
                        }. Reconnect GitLab with a new token.`}
                    </Text>
                )}
                {loadFailed && projects.length > 0 && (
                    <GitLabProjectsLoadError
                        onRetry={loadGitlabProjects}
                        retrying={gitlabProjectResultsLoading}
                        className="border-b"
                    />
                )}
                <ComboboxEmpty
                    className={cn(
                        'h-auto whitespace-normal',
                        (loading || loadFailed) && 'flex-col items-center justify-center gap-2 py-4'
                    )}
                >
                    {loading ? (
                        <>
                            <Spinner aria-hidden="true" />
                            <Text size="sm" variant="muted">
                                Loading GitLab projects
                            </Text>
                        </>
                    ) : loadFailed ? (
                        <GitLabProjectsLoadError
                            onRetry={loadGitlabProjects}
                            retrying={gitlabProjectResultsLoading}
                            className="flex-col text-center"
                        />
                    ) : (
                        'No GitLab projects found. Each GitLab project needs its own connection.'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(project: string) => (
                        <ComboboxItem key={project} value={project}>
                            <span className="min-w-0 break-all">{project}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

function GitLabProjectsLoadError({
    onRetry,
    retrying,
    className,
}: {
    onRetry: () => void
    retrying: boolean
    className: string
}): JSX.Element {
    return (
        <div className={cn('flex items-center gap-2 px-3 py-2', className)} data-attr="task-composer-gitlab-load-error">
            <Text size="xs" variant="muted">
                Couldn't load GitLab projects. Retry, or reconnect GitLab if this keeps happening.
            </Text>
            <Button
                variant="outline"
                size="xs"
                className="shrink-0"
                loading={retrying}
                // Keeps focus in the search field so the popup stays open.
                onMouseDown={(event) => event.preventDefault()}
                onClick={onRetry}
                data-attr="task-composer-gitlab-retry"
            >
                Retry
            </Button>
        </div>
    )
}

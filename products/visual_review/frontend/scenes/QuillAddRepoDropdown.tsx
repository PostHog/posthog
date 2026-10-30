import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxListFooter,
    ComboboxTrigger,
    Spinner,
} from '@posthog/quill'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { visualReviewSettingsSceneLogic } from './visualReviewSettingsSceneLogic'

export function QuillAddRepoDropdown(): JSX.Element {
    const { availableRepos, existingRepoNames, saving, githubManageAccessUrl } =
        useValues(visualReviewSettingsSceneLogic)
    const { addRepo } = useActions(visualReviewSettingsSceneLogic)
    const { githubRepositoriesLoading } = useValues(integrationsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    if (githubRepositoriesLoading && availableRepos.length === 0) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <Spinner /> Loading repositories...
            </div>
        )
    }

    const unaddedRepoNames = availableRepos
        .filter((r: GitHubRepoApi) => !existingRepoNames.has(r.full_name))
        .map((r: GitHubRepoApi) => r.full_name)
    const manageAccessUrl = githubManageAccessUrl ?? urls.settings('environment-integrations')

    return (
        <Combobox<string>
            items={unaddedRepoNames}
            value={null}
            onValueChange={(fullName) => {
                const repo = availableRepos.find((r: GitHubRepoApi) => r.full_name === fullName)
                if (repo) {
                    addRepo(repo)
                }
            }}
        >
            <ComboboxTrigger render={<Button ref={triggerRef} variant="outline" loading={saving} />}>
                Add a repository...
            </ComboboxTrigger>
            <ComboboxContent anchor={triggerRef} align="end" className="min-w-[280px]">
                <div className="p-1">
                    <ComboboxInput placeholder="Search repositories" showTrigger={false} className="w-full" />
                </div>
                <ComboboxEmpty>
                    {unaddedRepoNames.length === 0 ? 'No more repositories' : 'No repositories found'}
                </ComboboxEmpty>
                <ComboboxList>
                    {(fullName: string) => (
                        <ComboboxItem key={fullName} value={fullName}>
                            <span className="min-w-0 break-all">{fullName}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
                <ComboboxListFooter>
                    <Button
                        size="sm"
                        left
                        className="w-full text-muted"
                        render={
                            <LinkPrimitive to={manageAccessUrl} target={githubManageAccessUrl ? '_blank' : undefined} />
                        }
                    >
                        Manage access
                    </Button>
                </ComboboxListFooter>
            </ComboboxContent>
        </Combobox>
    )
}

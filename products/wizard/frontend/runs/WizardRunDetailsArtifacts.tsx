import { IconArrowRight, IconExternal, IconGitBranch, IconGithub } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
} from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunGitDiffArtifactApi } from '../generated/api.schemas'
import { formatArtifactSize } from '../wizardRunDisplay'
import { WizardRunDiffStats } from './WizardRunDiffStats'

export function WizardRunDetailsArtifacts({
    run,
    artifacts,
    error,
    loading,
    onOpenDiff,
    onRetry,
}: {
    run: WizardRunApi
    artifacts: WizardRunArtifactApi[]
    error: string | null
    loading: boolean
    onOpenDiff: (artifact: WizardRunGitDiffArtifactApi) => void
    onRetry: () => void
}): JSX.Element {
    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
            </div>
        )
    }

    if (error && artifacts.length === 0) {
        return (
            <Item tone="destructive" variant="outline">
                <ItemContent>
                    <ItemDescription>{error}</ItemDescription>
                    <Button variant="outline" size="sm" onClick={onRetry}>
                        Try again
                    </Button>
                </ItemContent>
            </Item>
        )
    }

    if (artifacts.length === 0) {
        return (
            <p className="m-0 text-sm text-muted">
                {run.status === 'created' || run.status === 'running'
                    ? 'Artifacts will appear here when the Wizard produces them.'
                    : 'This run did not produce any artifacts.'}
            </p>
        )
    }

    const pullRequest = artifacts.find((artifact) => artifact.artifact_type === 'pull_request')
    const gitDiff = artifacts.find((artifact) => artifact.artifact_type === 'git_diff')

    return (
        <ItemGroup className="gap-2">
            {pullRequest && (
                <Item
                    size="sm"
                    variant="outline"
                    className="hover:bg-fill-hover"
                    render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                >
                    <ItemMedia>
                        <IconGithub />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle className="text-foreground">Pull request #{pullRequest.number}</ItemTitle>
                        <ItemDescription className="flex min-w-0 items-center gap-1">
                            <IconGitBranch className="shrink-0" />
                            <span className="truncate">{pullRequest.base_branch}</span>
                            <IconArrowRight className="shrink-0" />
                            <span className="truncate">{pullRequest.head_branch}</span>
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <IconExternal className="size-4 shrink-0 text-muted" />
                    </ItemActions>
                </Item>
            )}
            {gitDiff && (
                <Item
                    size="sm"
                    variant="outline"
                    className="hover:bg-fill-hover"
                    render={
                        <button
                            type="button"
                            onClick={() => onOpenDiff(gitDiff)}
                            data-attr="wizard-run-open-git-diff"
                        />
                    }
                >
                    <ItemMedia>
                        <IconGitBranch />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle className="text-foreground">Git diff</ItemTitle>
                        <ItemDescription>{formatArtifactSize(gitDiff.size_bytes)}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <WizardRunDiffStats additions={gitDiff.additions} removals={gitDiff.removals} />
                        <IconArrowRight className="size-4 shrink-0 text-muted" />
                    </ItemActions>
                </Item>
            )}
        </ItemGroup>
    )
}

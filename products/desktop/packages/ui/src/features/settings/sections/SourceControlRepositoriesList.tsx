import {
  ArrowSquareOutIcon,
  GithubLogoIcon,
  GitlabLogoIcon,
} from "@phosphor-icons/react";
import type { GitProviderRepositoriesResult } from "@posthog/core/integrations/gitProviderService";
import {
  GIT_PROVIDER_CAPABILITIES,
  GIT_PROVIDER_LABELS,
  type GitProviderKind,
  type GitProviderRepository,
} from "@posthog/core/integrations/gitProviders";
import { Badge, Button, Text } from "@posthog/quill";
import {
  SettingsCard,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { useState } from "react";

const PROVIDER_ICONS: Record<GitProviderKind, typeof GithubLogoIcon> = {
  github: GithubLogoIcon,
  gitlab: GitlabLogoIcon,
};

interface SourceControlRepositoriesListProps {
  data: GitProviderRepositoriesResult;
  isPending: boolean;
  isError: boolean;
  isRefetching: boolean;
  hasRefreshError?: boolean;
  refetch: () => void;
}

const PAGE_SIZE = 50;

export function SourceControlRepositoriesList({
  data,
  isPending,
  isError,
  isRefetching,
  hasRefreshError,
  refetch,
}: SourceControlRepositoriesListProps) {
  const [pageIndex, setPageIndex] = useState(0);
  const lastPage = Math.max(
    0,
    Math.ceil(data.repositories.length / PAGE_SIZE) - 1,
  );
  const page = Math.min(pageIndex, lastPage);
  const repositories = data.repositories.slice(
    page * PAGE_SIZE,
    (page + 1) * PAGE_SIZE,
  );
  return (
    <SettingsSection
      label="Connected repositories"
      description="Every repository this project reaches through GitHub and GitLab"
      action={
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isRefetching}
          data-attr="connected-repositories-refresh"
          onClick={() => void refetch()}
        >
          {isRefetching ? <Spinner /> : null}
          Refresh
        </Button>
      }
    >
      <SettingsCard>
        {isPending ? (
          <div className="flex items-center gap-2 px-3.5 py-3">
            <Spinner size="sm" aria-hidden="true" />
            <Text size="xs" variant="muted">
              Loading…
            </Text>
          </div>
        ) : isError ? (
          <div className="px-3.5 py-3">
            <Text size="xs" className="text-destructive-foreground">
              Couldn't load repositories. Refresh to try again.
            </Text>
          </div>
        ) : data.repositories.length === 0 &&
          data.failedConnections.length === 0 ? (
          <div className="px-3.5 py-3">
            <Text size="xs" variant="muted">
              No repositories yet. Connect GitHub above, or connect a GitLab
              project in the PostHog project settings.
            </Text>
          </div>
        ) : (
          repositories.map((repository) => (
            <SourceControlRepositoryRow
              key={`${repository.provider}:${repository.integrationId}:${repository.fullName}`}
              repository={repository}
            />
          ))
        )}
        {!isError && hasRefreshError ? (
          <div className="px-3.5 py-2">
            <Text size="xs" className="text-destructive-foreground">
              Couldn't refresh repositories. Refresh to try again.
            </Text>
          </div>
        ) : null}
        {lastPage > 0 ? (
          <div className="flex items-center justify-between gap-3 px-3.5 py-2">
            <Text
              size="xs"
              variant="muted"
            >{`Page ${page + 1} of ${lastPage + 1}`}</Text>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-attr="connected-repositories-previous"
                disabled={page === 0}
                onClick={() => setPageIndex(page - 1)}
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-attr="connected-repositories-next"
                disabled={page === lastPage}
                onClick={() => setPageIndex(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
        {!isPending && data.pendingConnections.length > 0 ? (
          <div className="flex items-center gap-2 px-3.5 py-2">
            <Spinner size="sm" aria-hidden="true" />
            <Text size="xs" variant="muted">
              Loading more repositories…
            </Text>
          </div>
        ) : null}
        {data && data.failedConnections.length > 0 ? (
          <div className="px-3.5 py-2">
            <Text size="xs" className="text-destructive-foreground">
              Couldn't load repositories for{" "}
              {data.failedConnections
                .map((connection) => connection.label)
                .join(", ")}
              . Refresh to try again.
            </Text>
          </div>
        ) : null}
      </SettingsCard>
    </SettingsSection>
  );
}

function SourceControlRepositoryRow({
  repository,
}: {
  repository: GitProviderRepository;
}) {
  const Icon = PROVIDER_ICONS[repository.provider];
  const capabilities = GIT_PROVIDER_CAPABILITIES[repository.provider];

  return (
    <div className="flex min-h-11 items-center gap-3 px-3.5 py-2">
      <div className="shrink-0 text-muted-foreground">
        <Icon size={16} aria-label={GIT_PROVIDER_LABELS[repository.provider]} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate font-medium text-[13px] text-foreground leading-snug">
          {repository.fullName}
        </span>
        <span className="truncate text-[12px] text-muted-foreground leading-snug">
          {GIT_PROVIDER_LABELS[repository.provider]}
        </span>
      </div>
      {capabilities.cloudTasks ? null : (
        <Badge variant="default">Read only</Badge>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`Open ${repository.fullName}`}
        onClick={() => void openUrlInBrowser(repository.url)}
      >
        <ArrowSquareOutIcon size={12} />
      </Button>
    </div>
  );
}

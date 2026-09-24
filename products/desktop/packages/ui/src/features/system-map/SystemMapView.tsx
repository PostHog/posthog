import { ArrowClockwise, Graph } from "@phosphor-icons/react";
import { SYSTEM_MAP_FLAG } from "@posthog/core/system-map/schemas";
import type {
  SystemMapResult,
  SystemMapScope,
} from "@posthog/core/system-map/systemMapService";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/authQueries";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { FolderPicker } from "@posthog/ui/features/folder-picker/FolderPicker";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useActiveRepoStore } from "@posthog/ui/shell/activeRepoStore";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import {
  type ReactElement,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { SystemMapGraph } from "./SystemMapGraph";
import { useSavedSystemMap } from "./useSavedSystemMap";
import { useSystemMapAnalysis } from "./useSystemMapAnalysis";

export interface SystemMapPanelProps {
  repositoryPicker?: ReactNode;
  hasRepository: boolean;
  running: boolean;
  restoring?: boolean;
  result?: SystemMapResult;
  error?: string;
  onAnalyze: () => void;
  onCancel: () => void;
  onRetryLoad?: () => void;
  onInspect?: (kind: "area" | "component") => void;
}

export function SystemMapPanel({
  repositoryPicker,
  hasRepository,
  running,
  restoring = false,
  result,
  error,
  onAnalyze,
  onCancel,
  onRetryLoad,
  onInspect,
}: SystemMapPanelProps): ReactElement {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChromeBar
        inset="text"
        actions={
          running ? (
            <Button size="sm" variant="outline" onClick={onCancel}>
              Stop analysis
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              disabled={!hasRepository || restoring}
              onClick={onAnalyze}
            >
              {result ? <ArrowClockwise /> : <Graph />}
              {result ? "Analyze again" : "Analyze repository"}
            </Button>
          )
        }
      >
        <div className="min-w-0 flex-1 truncate">
          {repositoryPicker ?? "System map"}
        </div>
      </ChromeBar>
      {error && result && !running && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 border-border border-b px-4 py-2 text-sm"
        >
          <span>{error}</span>
          {onRetryLoad && (
            <Button
              size="sm"
              variant="outline"
              disabled={restoring}
              onClick={onRetryLoad}
            >
              Retry loading
            </Button>
          )}
        </div>
      )}
      {result ? (
        <SystemMapGraph map={result.map} onInspect={onInspect} />
      ) : (
        <Empty className="min-h-0 flex-1">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              {running || restoring ? (
                <Spinner aria-hidden="true" />
              ) : (
                <Graph />
              )}
            </EmptyMedia>
            <EmptyTitle>
              {running
                ? "Analyzing repository"
                : restoring
                  ? "Loading saved map"
                  : onRetryLoad
                    ? "Could not load saved map"
                    : error
                      ? "Analysis did not finish"
                      : "Explore your system"}
            </EmptyTitle>
            <EmptyDescription>
              {running
                ? "The agent is reading source files to find areas, components, and their connections. You can stop the analysis at any time."
                : restoring
                  ? "Loading the last successful scan for this repository."
                  : (error ??
                    "Select a repository, then analyze it to build a map. Zoom from areas to components and inspect the source behind each connection.")}
            </EmptyDescription>
          </EmptyHeader>
          {!running && !restoring && (
            <EmptyContent>
              {onRetryLoad && (
                <Button size="sm" variant="outline" onClick={onRetryLoad}>
                  Retry loading
                </Button>
              )}
              <p className="max-w-md text-center text-muted-foreground text-xs">
                Analysis uses your AI credits and can take a few minutes. This
                first version reads local repositories. Your last successful map
                loads when you reopen the repository. Sign-in and an internet
                connection are required.
              </p>
            </EmptyContent>
          )}
        </Empty>
      )}
      {result && (
        <div className="shrink-0 border-border border-t px-4 py-1.5 text-muted-foreground text-xs">
          Snapshot from {new Date(result.analyzedAt).toLocaleString()}. Analyze
          again after code changes.
        </div>
      )}
    </div>
  );
}

function RepositoryAnalysis({
  repoPath,
  repositoryPicker,
}: {
  repoPath: string;
  repositoryPicker: ReactNode;
}): ReactElement {
  const auth = useAuthStateValue((state) => state);
  const me = useMeQuery();
  const scope: SystemMapScope | null =
    repoPath && auth.cloudRegion && auth.currentProjectId && me.data?.uuid
      ? {
          repoPath,
          apiHost: getCloudUrlFromRegion(auth.cloudRegion),
          projectId: auth.currentProjectId,
          userId: me.data.uuid,
        }
      : null;
  const saved = useSavedSystemMap(scope);
  const analysis = useSystemMapAnalysis();
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  return (
    <SystemMapPanel
      repositoryPicker={repositoryPicker}
      hasRepository={!!scope}
      running={analysis.isPending}
      restoring={!!repoPath && (me.isLoading || saved.isFetching)}
      result={saved.data ?? undefined}
      error={
        analysis.error
          ? controller.current?.signal.aborted
            ? "Analysis stopped. Select Analyze repository to start again."
            : analysis.error.message
          : me.error || saved.error
            ? "Check your connection and retry, or analyze the repository again."
            : saved.data?.saveError
      }
      onAnalyze={() => {
        if (analysis.isPending || saved.isFetching || !scope) return;
        controller.current = new AbortController();
        analysis.mutate({
          ...scope,
          signal: controller.current.signal,
        });
      }}
      onCancel={() => controller.current?.abort()}
      onRetryLoad={
        me.error || saved.error
          ? () => {
              if (analysis.isPending || me.isFetching || saved.isFetching)
                return;
              if (me.error) void me.refetch();
              else void saved.refetch();
            }
          : undefined
      }
      onInspect={(kind) =>
        track(ANALYTICS_EVENTS.SYSTEM_MAP_INSPECTED, { kind })
      }
    />
  );
}

export function SystemMapView(): ReactElement {
  const enabled = useFeatureFlag(SYSTEM_MAP_FLAG, import.meta.env.DEV);
  const { localWorkspaces } = useHostCapabilities();
  const activeRepo = useActiveRepoStore((state) => state.path);
  const identity = useAuthStateValue(getAuthIdentity);
  const [repoPath, setRepoPath] = useState(activeRepo);
  if (!enabled || !localWorkspaces || !identity)
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Graph />
          </EmptyMedia>
          <EmptyTitle>System map unavailable</EmptyTitle>
          <EmptyDescription>
            Open PostHog Desktop and sign in with access to System map to
            analyze a local repository.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  return (
    <RepositoryAnalysis
      key={`${identity}:${repoPath}`}
      repoPath={repoPath}
      repositoryPicker={
        <FolderPicker
          value={repoPath}
          onChange={setRepoPath}
          placeholder="Select repository"
        />
      }
    />
  );
}

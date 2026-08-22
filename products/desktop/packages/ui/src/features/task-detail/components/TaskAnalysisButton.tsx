import { MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS, TASK_ANALYSIS_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { toast } from "@posthog/ui/primitives/toast";
import { useAuthenticatedMutation } from "../../../hooks/useAuthenticatedMutation";
import { Tooltip } from "../../../primitives/Tooltip";
import { navigateToTaskDetail } from "../../../router/navigationBridge";
import { track } from "../../../shell/analytics";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";

interface AnalyzeResult {
  analysis_task_id: string;
  created: boolean;
}

/**
 * Header action that asks the backend to analyze this task's latest run for
 * inefficiencies. The analysis runs as a separate PostHog-funded task; this
 * button only creates it and navigates there. Idempotent server-side, so a
 * second click opens the existing analysis instead of paying for another.
 */
export function TaskAnalysisButton({ task }: { task: Task }) {
  const enabled = useFeatureFlag(TASK_ANALYSIS_FLAG) || import.meta.env.DEV;
  const runId = task.latest_run?.id;
  const isAnalyzableOrigin = task.origin_product !== "task_analysis";

  const mutation = useAuthenticatedMutation<AnalyzeResult, Error, void>(
    (client) => {
      if (!runId) throw new Error("This task has no run to analyze yet.");
      return client.analyzeTaskRun(task.id, runId);
    },
    {
      onSuccess: (result) => {
        track(ANALYTICS_EVENTS.TASK_ANALYSIS_REQUESTED, {
          task_id: task.id,
          run_id: runId ?? "",
          created: result.created,
        });
        toast.success(
          result.created
            ? "Analyzing this run. The report will appear on the analysis task."
            : "An analysis for this run already exists. Opening it.",
        );
        navigateToTaskDetail(result.analysis_task_id);
      },
      onError: (error) => {
        toastError("Could not analyze this run", error);
      },
    },
  );

  if (!enabled || !runId || !isAnalyzableOrigin) return null;

  return (
    <Tooltip content="Analyze this run for inefficiencies" side="bottom">
      <Button
        size="icon-sm"
        variant="outline"
        aria-label="Analyze this run"
        onClick={() => mutation.mutate()}
        loading={mutation.isPending}
        disabled={mutation.isPending}
      >
        <MagnifyingGlass size={16} />
      </Button>
    </Tooltip>
  );
}

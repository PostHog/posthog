import { Button } from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  isTerminalStatus,
  TASK_ANALYSIS_FLAG,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { toast } from "@posthog/ui/primitives/toast";
import { useAuthenticatedMutation } from "../../../hooks/useAuthenticatedMutation";
import { navigateToTaskDetail } from "../../../router/navigationBridge";
import { track } from "../../../shell/analytics";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";

interface AnalyzeResult {
  analysis_task_id: string;
  created: boolean;
}

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

  if (
    !enabled ||
    !runId ||
    !isAnalyzableOrigin ||
    !isTerminalStatus(task.latest_run?.status)
  )
    return null;

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => mutation.mutate()}
      loading={mutation.isPending}
      disabled={mutation.isPending}
    >
      Run analysis
    </Button>
  );
}

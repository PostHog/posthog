import {
  Cloud,
  GitCommit,
  Laptop,
  Spinner,
  StopCircle,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { PRBadgeLink } from "@posthog/ui/features/git-interaction/components/PRBadgeLink";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { Meta, StoryObj } from "@storybook/react-vite";

const STORY_PR_URL = "https://github.com/example/example-repo/pull/90175";

type TaskRunActionScenario =
  | "local"
  | "cloud-running"
  | "cloud-running-with-pr"
  | "cloud-stopping"
  | "cloud-complete";

interface TaskRunActionsBannerStoryProps {
  scenario: TaskRunActionScenario;
}

function TaskRunActionsPreview({ scenario }: TaskRunActionsBannerStoryProps) {
  const isLocal = scenario === "local";
  const isRunning = scenario.startsWith("cloud-running");
  const isStopping = scenario === "cloud-stopping";
  const hasPullRequest =
    scenario === "cloud-running-with-pr" ||
    scenario === "cloud-stopping" ||
    scenario === "cloud-complete";

  return (
    <div className="flex w-full flex-wrap items-center justify-end gap-1">
      <Button size="sm">
        {isLocal ? <Cloud size={14} /> : <Laptop size={14} />}
        {isLocal ? "Continue in cloud" : "Continue locally"}
      </Button>
      {isLocal && (
        <Button variant="outline" size="sm">
          <GitCommit size={14} />
          Commit
        </Button>
      )}
      {(isRunning || isStopping) && (
        <Button variant="outline" size="sm" disabled={isStopping}>
          {isStopping ? (
            <Spinner size={14} className="animate-spin" />
          ) : (
            <StopCircle size={14} />
          )}
          {isStopping ? "Stopping..." : "Stop run"}
        </Button>
      )}
      {hasPullRequest && (
        <PRBadgeLink
          prUrl={STORY_PR_URL}
          prState="OPEN"
          merged={false}
          draft={false}
        />
      )}
    </div>
  );
}

function TaskRunActionsBannerStory({
  scenario,
}: TaskRunActionsBannerStoryProps) {
  return (
    <div className="max-w-[800px]">
      <PromptInput
        sessionId={`task-actions-${scenario}`}
        initialContent="Move the task actions next to the prompt"
        onSubmit={() => {}}
        headerStrip={<TaskRunActionsPreview scenario={scenario} />}
      />
    </div>
  );
}

const meta: Meta<typeof TaskRunActionsBannerStory> = {
  title: "Features/TaskDetail/TaskRunActionsBanner",
  component: TaskRunActionsBannerStory,
  parameters: { layout: "padded" },
};

export default meta;
type Story = StoryObj<typeof TaskRunActionsBannerStory>;

export const LocalRun: Story = {
  args: { scenario: "local" },
};

export const CloudRun: Story = {
  args: { scenario: "cloud-running" },
};

export const CloudRunWithPullRequest: Story = {
  args: { scenario: "cloud-running-with-pr" },
};

export const CloudRunStopping: Story = {
  args: { scenario: "cloud-stopping" },
};

export const CompletedCloudRun: Story = {
  args: { scenario: "cloud-complete" },
};

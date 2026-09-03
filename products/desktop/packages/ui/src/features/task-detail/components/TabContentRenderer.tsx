import type { Task } from "@posthog/shared/domain-types";
import { AutoresearchPanel } from "../../autoresearch/AutoresearchPanel";
import { CodeEditorPanel } from "../../code-editor/components/CodeEditorPanel";
import {
  LazyCloudReviewPage as CloudReviewPage,
  LazyReviewPage as ReviewPage,
} from "../../code-review/components/LazyReviewPages";
import type { Tab } from "../../panels/panelTypes";
import { PiSessionView } from "../../pi-sessions/PiSessionView";
import { PostHogObjectPage } from "../../posthog-objects/PostHogObjectPage";
import { ArtifactPreview } from "../../sessions/components/ArtifactPreview";
import { useIsCloudTask } from "../../workspace/useWorkspace";
import { ActionPanel } from "./ActionPanel";
import { CanvasInstructionsTab } from "./CanvasInstructionsTab";
import { ChangesPanel } from "./ChangesPanel";
import { ChannelContextTab } from "./ChannelContextTab";
import { FileTreePanel } from "./FileTreePanel";
import { TaskLogsPanel } from "./TaskLogsPanel";
import { TaskShellPanel } from "./TaskShellPanel";

interface TabContentRendererProps {
  tab: Tab;
  taskId: string;
  task: Task;
}

export function TabContentRenderer({
  tab,
  taskId,
  task,
}: TabContentRendererProps) {
  const isCloud = useIsCloudTask(task);
  const { data } = tab;

  switch (data.type) {
    case "logs":
      return task.runtime === "pi" ? (
        <PiSessionView key={taskId} task={task} isCloud={isCloud} />
      ) : (
        <TaskLogsPanel taskId={taskId} task={task} />
      );

    case "terminal":
      return (
        <TaskShellPanel taskId={taskId} task={task} shellId={data.terminalId} />
      );

    case "file":
      return (
        <CodeEditorPanel
          taskId={taskId}
          task={task}
          absolutePath={data.absolutePath}
        />
      );

    case "review": {
      return isCloud ? (
        <CloudReviewPage task={task} />
      ) : (
        <ReviewPage task={task} />
      );
    }

    case "action":
      return (
        <ActionPanel
          taskId={taskId}
          actionId={data.actionId}
          command={data.command}
          cwd={data.cwd}
        />
      );

    case "context":
      return (
        <ChannelContextTab channelName={data.channelName} body={data.body} />
      );

    case "canvas-instructions":
      return <CanvasInstructionsTab body={data.body} />;

    case "autoresearch":
      return <AutoresearchPanel taskId={taskId} />;

    case "artifact":
      return (
        <ArtifactPreview
          taskId={taskId}
          runId={data.runId}
          artifactId={data.artifactId}
          name={tab.label}
        />
      );

    case "posthog-object":
      return (
        <PostHogObjectPage
          metadata={{
            object_kind: data.objectKind,
            object_id: data.objectId,
          }}
          fallbackName={tab.label}
        />
      );

    case "other":
      switch (tab.id) {
        case "files":
          return <FileTreePanel taskId={taskId} task={task} />;
        case "changes":
          return <ChangesPanel taskId={taskId} task={task} />;
        default:
          return <div>Unknown tab: {tab.id}</div>;
      }

    default:
      return <div>Unknown tab type</div>;
  }
}

import type { Task } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Tab } from "../../panels/panelTypes";
import { TabContentRenderer } from "./TabContentRenderer";

vi.mock("../../autoresearch/AutoresearchPanel", () => ({
  AutoresearchPanel: (): null => null,
}));
vi.mock("../../code-editor/components/CodeEditorPanel", () => ({
  CodeEditorPanel: (): null => null,
}));
vi.mock("../../code-review/components/LazyReviewPages", () => ({
  LazyCloudReviewPage: (): null => null,
  LazyReviewPage: (): null => null,
}));
vi.mock("../../sessions/components/ArtifactPreview", () => ({
  ArtifactPreview: (): null => null,
}));
vi.mock("../../workspace/useWorkspace", () => ({
  useIsCloudTask: () => false,
}));
vi.mock("./ActionPanel", () => ({ ActionPanel: (): null => null }));
vi.mock("./CanvasInstructionsTab", () => ({
  CanvasInstructionsTab: (): null => null,
}));
vi.mock("./ChangesPanel", () => ({ ChangesPanel: (): null => null }));
vi.mock("./ChannelContextTab", () => ({
  ChannelContextTab: (): null => null,
}));
vi.mock("./FileTreePanel", () => ({ FileTreePanel: (): null => null }));
vi.mock("./TaskShellPanel", () => ({ TaskShellPanel: (): null => null }));

vi.mock("../../pi-sessions/PiSessionView", () => ({
  PiSessionView: ({
    taskId,
    taskRunId,
  }: {
    taskId: string;
    taskRunId?: string;
  }): ReactElement => (
    <div data-testid="pi-session">
      {taskId}:{taskRunId}
    </div>
  ),
}));

vi.mock("./TaskLogsPanel", () => ({
  TaskLogsPanel: (): ReactElement => <div data-testid="acp-session" />,
}));

const logsTab: Tab = {
  id: "logs",
  label: "Chat",
  data: { type: "logs" },
};

function task(runtime: "pi" | "acp"): Task {
  return {
    id: "task-1",
    runtime,
    latest_run: { id: "run-1" },
  } as Task;
}

describe("TabContentRenderer", () => {
  it.each([
    { runtime: "pi" as const, expected: "pi-session", absent: "acp-session" },
    { runtime: "acp" as const, expected: "acp-session", absent: "pi-session" },
  ])(
    "renders the $runtime chat inside the panel",
    ({ runtime, expected, absent }) => {
      render(
        <TabContentRenderer
          tab={logsTab}
          taskId="task-1"
          task={task(runtime)}
        />,
      );

      expect(screen.getByTestId(expected)).toBeInTheDocument();
      expect(screen.queryByTestId(absent)).not.toBeInTheDocument();
    },
  );
});

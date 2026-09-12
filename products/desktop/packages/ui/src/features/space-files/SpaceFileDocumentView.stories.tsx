import type { SpaceFile } from "@posthog/api-client/posthog-client";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SpaceFileDocumentView } from "./SpaceFileDocumentView";

const file: SpaceFile = {
  id: "file-1",
  channel_id: "space-1",
  name: "todo.md",
  content: "# TODO\n\n- Review the current work\n- Update this list",
  version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const meta: Meta<typeof SpaceFileDocumentView> = {
  title: "Space files/SpaceFileDocumentView",
  component: SpaceFileDocumentView,
  args: {
    state: "document",
    file,
    sourceVisible: false,
    editing: false,
    saving: false,
    draft: file.content,
    conflict: false,
    saveError: null,
    onToggleSource: () => {},
    onEdit: () => {},
    onCancel: () => {},
    onSave: () => {},
    onDraftChange: () => {},
    onSelectionChange: () => {},
    onReload: () => {},
  },
  decorators: [
    (Story) => (
      <div className="h-[560px] border border-border">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SpaceFileDocumentView>;

export const Document: Story = {};

export const Conflict: Story = {
  args: { conflict: true, sourceVisible: true, editing: true },
};

export const Loading: Story = {
  args: { state: "loading", file: undefined },
};

export const ErrorState: Story = {
  args: {
    state: "error",
    file: undefined,
    error: new Error("Request failed"),
  },
};

export const Empty: Story = {
  args: { state: "empty", file: undefined },
};

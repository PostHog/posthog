import type { Task } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const currentUserId = vi.hoisted(() => ({ id: 1 as number | undefined }));
const mockHandoffMutate = vi.hoisted(() => vi.fn());
const mockMembers = vi.hoisted(() => ({
  members: [
    { id: 1, uuid: "u-1", email: "owner@example.com", first_name: "Owner" },
    { id: 2, uuid: "u-2", email: "colleague@example.com", first_name: "Col" },
    { id: 3, uuid: "u-3", email: "pepper@example.com", first_name: "Pepper" },
  ],
}));
const mockChannels = vi.hoisted(() => ({
  channels: [] as Array<{ id: string; channelType: string }>,
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { id: currentUserId.id } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({ members: mockMembers.members, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mockChannels.channels }),
}));
vi.mock("@posthog/ui/features/tasks/useTaskMutations", () => ({
  useHandoffTask: () => ({ mutate: mockHandoffMutate, isPending: false }),
}));
vi.mock("../../../primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { HandoffTaskDialog } from "./HandoffTaskDialog";

function createTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Fix the thing",
    description: "",
    created_at: "2026-05-28T00:00:00.000Z",
    updated_at: "2026-05-28T00:00:00.000Z",
    origin_product: "user_created",
    created_by: { id: 1, uuid: "u-1", email: "owner@example.com" },
    channel: null,
    ...overrides,
  };
}

function renderDialog(task: Task, open = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(
    <HandoffTaskDialog task={task} open={open} onOpenChange={() => {}} />,
    { wrapper },
  );
}

describe("HandoffTaskDialog", () => {
  it("keeps the confirm disabled until a person is picked", async () => {
    // Only the recipient can undo a handoff, so a confirm with no pick must not fire.
    mockHandoffMutate.mockClear();
    const user = userEvent.setup();
    renderDialog(createTask());

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByRole("button", { name: "Hand off" }),
    ).toHaveAttribute("aria-disabled", "true");
    await user.keyboard("{Enter}");
    expect(mockHandoffMutate).not.toHaveBeenCalled();
  });

  it("explains that a personal-space task moves to the recipient", async () => {
    renderDialog(createTask({ channel: null }));

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/moves into their personal space/i),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/only they can hand it back/i),
    ).toBeInTheDocument();
  });

  it("filters people by name or email as you type in the field", async () => {
    const user = userEvent.setup();
    renderDialog(createTask());
    await screen.findByRole("alertdialog");

    await user.click(screen.getByRole("combobox", { name: /hand off to/i }));
    expect(await screen.findByText("Col")).toBeInTheDocument();
    await user.keyboard("pepp");

    expect(await screen.findByText("Pepper")).toBeInTheDocument();
    expect(screen.queryByText("Col")).not.toBeInTheDocument();
  });

  it("does not offer the current owner as a handoff target", async () => {
    const user = userEvent.setup();
    renderDialog(createTask());
    await screen.findByRole("alertdialog");

    await user.click(screen.getByRole("combobox", { name: /hand off to/i }));
    expect(await screen.findByText("Col")).toBeInTheDocument();
    expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
  });

  it("shows the picked person in the field", async () => {
    const user = userEvent.setup();
    renderDialog(createTask());
    await screen.findByRole("alertdialog");

    await user.click(screen.getByRole("combobox", { name: /hand off to/i }));
    await user.click(await screen.findByText("Col"));

    expect(screen.getByRole("combobox", { name: /hand off to/i })).toHaveValue(
      "Col",
    );
  });

  it("hands off to the selected member only after the acknowledge checkbox", async () => {
    mockHandoffMutate.mockClear();
    const user = userEvent.setup();
    renderDialog(createTask());
    const dialog = await screen.findByRole("alertdialog");

    await user.click(screen.getByRole("combobox", { name: /hand off to/i }));
    await user.click(await screen.findByText("Col"));
    // A pick alone isn't enough: the checkbox is what says they really read it.
    expect(
      within(dialog).getByRole("button", { name: "Hand off" }),
    ).toHaveAttribute("aria-disabled", "true");
    await user.click(
      within(dialog).getByRole("checkbox", { name: /can't undo this/i }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Hand off" }));

    expect(mockHandoffMutate).toHaveBeenCalledWith(
      { taskId: "task-1", userId: 2 },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});

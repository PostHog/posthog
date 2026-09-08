import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceModeSelect } from "./WorkspaceModeSelect";

const cloudTargetOptionsState = vi.hoisted(() => ({
  options: [
    {
      key: "default",
      target: { kind: "default" as const },
      name: "Default",
      description: "Full network access",
    },
  ],
  favoriteKey: null,
  toggleFavorite: vi.fn(),
}));

vi.mock("@posthog/ui/features/settings/adapterSubscription", () => ({
  useAdapterSubscription: () => ({
    flagEnabled: false,
    subscriptionOn: false,
    loggedIn: false,
  }),
}));
vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  openSettings: vi.fn(),
}));
vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: true }),
}));
vi.mock("../hooks/useCloudModeEnabled", () => ({
  useCloudModeEnabled: () => true,
}));
vi.mock("../hooks/useCloudTarget", () => ({
  useCloudTargetOptions: () => cloudTargetOptionsState,
}));
vi.mock("./CloudGithubSetupDialog", () => ({
  CloudGithubSetupDialog: ({
    onConnected,
    onClose,
  }: {
    onConnected: () => void;
    onClose: () => void;
  }) => (
    <div role="alertdialog">
      <button type="button" onClick={onConnected}>
        Complete GitHub connection
      </button>
      <button type="button" onClick={onClose}>
        Cancel
      </button>
    </div>
  ),
}));

describe("WorkspaceModeSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens GitHub setup before selecting Cloud", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WorkspaceModeSelect
        value="local"
        onChange={onChange}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration={false}
        isLoadingGithubIntegration={false}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Workspace mode" });
    await user.click(trigger);

    expect(await screen.findByText("Run location")).toBeInTheDocument();
    expect(screen.getByText("Run in a cloud sandbox")).toBeInTheDocument();
    expect(screen.getByText("Connect GitHub")).toBeInTheDocument();

    await user.click(screen.getByText("Cloud"));

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("preserves the previous mode when the user cancels GitHub setup", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WorkspaceModeSelect
        value="local"
        onChange={onChange}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration={false}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Workspace mode" });
    await user.click(trigger);
    await user.click(await screen.findByText("Cloud"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveTextContent("Local");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("selects Cloud after GitHub connects", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WorkspaceModeSelect
        value="local"
        onChange={onChange}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Workspace mode" }));
    await user.click(await screen.findByText("Cloud"));
    await user.click(
      screen.getByRole("button", { name: "Complete GitHub connection" }),
    );

    expect(onChange).toHaveBeenCalledWith("cloud");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("selects Cloud directly when GitHub is connected", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <WorkspaceModeSelect
        value="local"
        onChange={onChange}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration
      />,
    );

    await user.click(screen.getByRole("button", { name: "Workspace mode" }));

    expect(
      await screen.findByText("Run in a cloud sandbox"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Connect GitHub")).not.toBeInTheDocument();

    await user.click(screen.getByText("Cloud"));
    expect(onChange).toHaveBeenCalledWith("cloud");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("does not show the setup requirement while GitHub is loading", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceModeSelect
        value="local"
        onChange={vi.fn()}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration={false}
        isLoadingGithubIntegration
      />,
    );

    await user.click(screen.getByRole("button", { name: "Workspace mode" }));

    expect(
      await screen.findByText("Run in a cloud sandbox"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Connect GitHub")).not.toBeInTheDocument();
  });

  it("keeps the standard Cloud trigger label", () => {
    render(
      <WorkspaceModeSelect
        value="cloud"
        onChange={vi.fn()}
        overrideModes={["local", "cloud"]}
        hasGithubIntegration={false}
        isLoadingGithubIntegration={false}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Workspace mode" }),
    ).toHaveTextContent("Cloud");
    expect(
      screen.getByRole("button", { name: "Workspace mode" }),
    ).not.toHaveTextContent("Requires GitHub");
  });
});

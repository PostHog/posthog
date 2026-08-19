import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reportId: "report-id" as string | undefined,
  pathname: "/code/inbox/reports/report-id",
  openReport: vi.fn(),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useOpenInboxReport", () => ({
  useOpenInboxReport: () => mocks.openReport,
}));
vi.mock("@posthog/ui/features/inbox/components/InboxView", () => ({
  InboxView: () => <div>Inbox content</div>,
}));
vi.mock("@posthog/ui/router/routeSkeletons", () => ({
  AppPageSkeleton: () => null,
  withRouteSkeleton: () => ({}),
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: { component: () => ReactElement }) => ({
    options,
  }),
  useLocation: () => ({ pathname: mocks.pathname }),
  useParams: () => ({ reportId: mocks.reportId }),
}));

import { Route } from "./inbox";

const InboxRoute = Route.options.component as () => ReactElement;

describe("InboxRoute", () => {
  beforeEach(() => {
    mocks.reportId = "report-id";
    mocks.pathname = "/code/inbox/reports/report-id";
    mocks.openReport.mockClear();
  });

  it("keeps Inbox visible while resolving a report without a canvas", () => {
    render(<InboxRoute />);

    expect(screen.getByText("Inbox content")).toBeInTheDocument();
    expect(mocks.openReport).toHaveBeenCalledWith("report-id");
  });

  it("opens an eligible report once while keeping Inbox mounted", () => {
    const { rerender } = render(<InboxRoute />);
    rerender(<InboxRoute />);

    expect(mocks.openReport).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Inbox content")).toBeInTheDocument();
  });

  it.each(["pulls", "reports", "dismissed", "runs", "agents"])(
    "keeps the %s list route in Inbox",
    (tab) => {
      mocks.reportId = undefined;
      mocks.pathname = `/code/inbox/${tab}`;

      render(<InboxRoute />);

      expect(screen.getByText("Inbox content")).toBeInTheDocument();
      expect(mocks.openReport).not.toHaveBeenCalled();
    },
  );

  it("does not treat an agent run as a Signal report", () => {
    mocks.pathname = "/code/inbox/runs/report-id";

    render(<InboxRoute />);

    expect(mocks.openReport).not.toHaveBeenCalled();
  });
});

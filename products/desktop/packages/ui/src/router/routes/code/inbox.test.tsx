import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reportId: "report-id" as string | undefined,
  reportSpaceId: "general-id" as string | null,
  openReport: vi.fn(),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useReportSpace", () => ({
  useReportSpace: () => ({ reportSpaceId: mocks.reportSpaceId }),
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
  Navigate: () => <div>Redirected</div>,
  useParams: () => ({ reportId: mocks.reportId }),
}));

import { Route } from "./inbox";

const InboxRoute = Route.options.component as () => ReactElement;

describe("InboxRoute", () => {
  beforeEach(() => {
    mocks.reportId = "report-id";
    mocks.reportSpaceId = "general-id";
    mocks.openReport.mockClear();
  });

  it("keeps Inbox visible while resolving a report without a canvas", () => {
    render(<InboxRoute />);

    expect(screen.getByText("Inbox content")).toBeInTheDocument();
    expect(mocks.openReport).toHaveBeenCalledWith("report-id");
  });

  it("opens a report once when its space becomes available", () => {
    mocks.reportSpaceId = null;
    const { rerender } = render(<InboxRoute />);
    expect(mocks.openReport).not.toHaveBeenCalled();

    mocks.reportSpaceId = "general-id";
    rerender(<InboxRoute />);
    rerender(<InboxRoute />);

    expect(mocks.openReport).toHaveBeenCalledTimes(1);
  });
});

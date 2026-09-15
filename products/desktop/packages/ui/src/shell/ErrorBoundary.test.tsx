import {
  isNotAuthenticatedError,
  NotAuthenticatedError,
} from "@posthog/shared";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

vi.mock("@posthog/ui/shell/analytics", () => ({
  captureException: vi.fn(),
}));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      error: vi.fn(),
      warn: vi.fn(),
      info: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import { captureException } from "@posthog/ui/shell/analytics";

function Thrower({ error }: { error: Error | null }) {
  if (error) throw error;
  return <div>ok</div>;
}

function Boundary(props: {
  children: ReactNode;
  resetKey?: unknown;
  shouldSuppress?: (e: Error) => boolean;
  fallback?: ReactNode;
}) {
  return (
    <ErrorBoundary
      resetKey={props.resetKey}
      shouldSuppress={props.shouldSuppress}
      fallback={props.fallback}
    >
      {props.children}
    </ErrorBoundary>
  );
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(captureException).mockClear();
});

describe("ErrorBoundary", () => {
  it("renders children when no error is thrown", () => {
    render(
      <Boundary>
        <Thrower error={null} />
      </Boundary>,
    );
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("hides error details until requested and reports telemetry", async () => {
    const user = userEvent.setup();
    render(
      <Boundary>
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("PostHog ran into an error")).toBeInTheDocument();
    expect(screen.queryByText(/Error: boom/)).not.toBeInTheDocument();
    expect(captureException).toHaveBeenCalledTimes(1);

    await user.click(
      screen.getByRole("button", { name: /show error details/i }),
    );
    expect(screen.getByText(/Error: boom/)).toBeInTheDocument();
  });

  it("renders custom fallback when provided", () => {
    render(
      <Boundary fallback={<div>custom fallback</div>}>
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("custom fallback")).toBeInTheDocument();
  });

  it("suppresses errors that match shouldSuppress (renders null, no telemetry)", () => {
    render(
      <Boundary shouldSuppress={isNotAuthenticatedError}>
        <Thrower error={new NotAuthenticatedError()} />
      </Boundary>,
    );
    expect(
      screen.queryByText("PostHog ran into an error"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("ok")).not.toBeInTheDocument();
    expect(captureException).not.toHaveBeenCalled();
  });

  it("does not suppress non-matching errors", () => {
    render(
      <Boundary shouldSuppress={isNotAuthenticatedError}>
        <Thrower error={new Error("other failure")} />
      </Boundary>,
    );
    expect(screen.getByText("PostHog ran into an error")).toBeInTheDocument();
    expect(captureException).toHaveBeenCalledTimes(1);
  });

  it("clears error state when resetKey changes", () => {
    const { rerender } = render(
      <Boundary resetKey="a">
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("PostHog ran into an error")).toBeInTheDocument();

    rerender(
      <Boundary resetKey="b">
        <Thrower error={null} />
      </Boundary>,
    );
    expect(
      screen.queryByText("PostHog ran into an error"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("refreshes the app from the error screen", async () => {
    const user = userEvent.setup();
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });

    render(
      <Boundary>
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    await user.click(screen.getByRole("button", { name: /^refresh$/i }));

    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("isNotAuthenticatedError", () => {
  it("matches NotAuthenticatedError instances", () => {
    expect(isNotAuthenticatedError(new NotAuthenticatedError())).toBe(true);
  });

  it("matches plain objects with the same name (e.g. tRPC-serialized errors)", () => {
    expect(isNotAuthenticatedError({ name: "NotAuthenticatedError" })).toBe(
      true,
    );
  });

  it("does not match unrelated errors", () => {
    expect(isNotAuthenticatedError(new Error("Not authenticated"))).toBe(false);
    expect(isNotAuthenticatedError(null)).toBe(false);
    expect(isNotAuthenticatedError("Not authenticated")).toBe(false);
  });
});

import {
  isNotAuthenticatedError,
  NotAuthenticatedError,
} from "@posthog/shared";
import { Theme } from "@radix-ui/themes";
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
    <Theme>
      <ErrorBoundary
        resetKey={props.resetKey}
        shouldSuppress={props.shouldSuppress}
        fallback={props.fallback}
      >
        {props.children}
      </ErrorBoundary>
    </Theme>
  );
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
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

  it("renders the default fallback UI on error and reports telemetry", () => {
    render(
      <Boundary>
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(captureException).toHaveBeenCalledTimes(1);
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
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
    expect(screen.queryByText("ok")).not.toBeInTheDocument();
    expect(captureException).not.toHaveBeenCalled();
  });

  it("does not suppress non-matching errors", () => {
    render(
      <Boundary shouldSuppress={isNotAuthenticatedError}>
        <Thrower error={new Error("other failure")} />
      </Boundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(captureException).toHaveBeenCalledTimes(1);
  });

  it("clears error state when resetKey changes", () => {
    const { rerender } = render(
      <Boundary resetKey="a">
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();

    rerender(
      <Boundary resetKey="b">
        <Thrower error={null} />
      </Boundary>,
    );
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("recovers via retry button", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <Boundary>
        <Thrower error={new Error("boom")} />
      </Boundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();

    rerender(
      <Boundary>
        <Thrower error={null} />
      </Boundary>,
    );
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("ok")).toBeInTheDocument();
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

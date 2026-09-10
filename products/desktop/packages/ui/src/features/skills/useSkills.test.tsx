import type { SkillInfo } from "@posthog/shared";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listFn = vi.hoisted(() => vi.fn());
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    skills: {
      list: {
        queryOptions: (_input: unknown, options: Record<string, unknown>) => ({
          queryKey: ["skills", "list"],
          queryFn: () => listFn(),
          ...options,
        }),
      },
    },
  }),
}));

import { useSkills } from "./useSkills";

const skills = [
  { name: "Commit", source: "user", path: "/skills/commit" },
  { name: "Review", source: "bundled", path: "/skills/review" },
] as unknown as SkillInfo[];

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useSkills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listFn.mockResolvedValue(skills);
  });

  it("returns the skills listed by the host client", async () => {
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(skills);
    expect(listFn).toHaveBeenCalledTimes(1);
  });
});

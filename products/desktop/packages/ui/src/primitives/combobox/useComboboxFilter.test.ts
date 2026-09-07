import { useComboboxFilter } from "@posthog/ui/primitives/combobox/useComboboxFilter";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("useComboboxFilter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const items = ["alpha", "beta", "gamma", "delta"];

  it("returns all items unfiltered when query is empty", () => {
    const { result } = renderHook(() =>
      useComboboxFilter(items, { open: true }),
    );
    expect(result.current.filtered).toEqual(items);
    expect(result.current.hasMore).toBe(false);
  });

  it("debounces the search before filtering", () => {
    const { result } = renderHook(() =>
      useComboboxFilter(items, { open: true }),
    );

    act(() => {
      result.current.onSearchChange("alp");
    });
    expect(result.current.filtered).toEqual(items);

    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(result.current.filtered).toEqual(["alpha"]);
  });

  it("clears the query immediately when the popover closes so reopen starts clean", () => {
    const { result, rerender } = renderHook(
      ({ open }) => useComboboxFilter(items, { open }),
      { initialProps: { open: true } },
    );

    act(() => {
      result.current.onSearchChange("alp");
    });
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(result.current.filtered).toEqual(["alpha"]);

    rerender({ open: false });
    rerender({ open: true });
    expect(result.current.filtered).toEqual(items);
  });

  it("respects the limit and reports hasMore", () => {
    const many = Array.from({ length: 60 }, (_, i) => `item-${i}`);
    const { result } = renderHook(() =>
      useComboboxFilter(many, { open: true, limit: 10 }),
    );
    expect(result.current.filtered).toHaveLength(10);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.moreCount).toBe(50);
  });

  it("places pinned values first regardless of score", () => {
    const { result } = renderHook(() =>
      useComboboxFilter(items, { open: true, pinned: ["gamma"] }),
    );
    expect(result.current.filtered[0]).toBe("gamma");
  });

  describe("weighted multi-key search (keys option)", () => {
    interface Skill {
      name: string;
      description: string;
    }
    const skills: Skill[] = [
      { name: "deploy-app", description: "Ship code to production" },
      { name: "run-tests", description: "Deploy a test runner and report" },
      { name: "lint", description: "Check formatting" },
    ];
    const keys = [
      { name: "name" as const, weight: 0.7 },
      { name: "description" as const, weight: 0.3 },
    ];
    const getValue = (s: Skill) => `${s.name} ${s.description}`;

    const runSearch = (query: string) => {
      const { result } = renderHook(() =>
        useComboboxFilter(skills, { open: true, keys }, getValue),
      );
      act(() => {
        result.current.onSearchChange(query);
      });
      act(() => {
        vi.advanceTimersByTime(150);
      });
      return result.current.filtered;
    };

    it("ranks a name match above a description-only match", () => {
      // "deploy" hits deploy-app's name (weight 0.7) and run-tests' description
      // (weight 0.3); the name match must win.
      const filtered = runSearch("deploy");
      expect(filtered.map((s) => s.name)).toEqual(["deploy-app", "run-tests"]);
    });

    it("promotes prefix matches for exact-match priority", () => {
      const prefixFirst: Skill[] = [
        { name: "unit-test", description: "Runs the unit suite" },
        { name: "test-runner", description: "Generic harness" },
      ];
      const { result } = renderHook(() =>
        useComboboxFilter(prefixFirst, { open: true, keys }, getValue),
      );
      act(() => {
        result.current.onSearchChange("test");
      });
      act(() => {
        vi.advanceTimersByTime(150);
      });
      // Both names contain "test", but only "test-runner" starts with it.
      expect(result.current.filtered[0]?.name).toBe("test-runner");
    });
  });
});

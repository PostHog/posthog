import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import {
  redirectFromLegacyPath,
  rewriteLegacyHref,
  rewriteLegacyPath,
} from "./legacyPaths";

describe("rewriteLegacyPath", () => {
  // Old hrefs outlive the route flatten: saved startup locations, deep links,
  // shared links, notifications. Each has to land on the page it named.
  it.each([
    ["/website", "/spaces"],
    ["/website/eng", "/spaces/eng"],
    ["/website/eng/loops", "/spaces/eng/loops"],
    ["/website/eng/tasks/t1", "/spaces/eng/tasks/t1"],
    ["/website/eng/dashboards/d1", "/spaces/eng/dashboards/d1"],
    ["/website/home", "/"],
    ["/website/activity", "/activity"],
    ["/website/command-center", "/command-center"],
    ["/website/mcp-servers", "/mcp-servers"],
    ["/website/skills", "/skills"],
    ["/website/feeds/f1", "/feeds/f1"],
    ["/website/new", "/new"],
    ["/code", "/new"],
    ["/code/inbox/pulls/42", "/inbox/pulls/42"],
    ["/code/agents/scouts/flaky", "/agents/scouts/flaky"],
    ["/code/archived", "/archived"],
    ["/code/loops/abc/edit", "/loops/abc/edit"],
    ["/code/tasks/t1", "/tasks/t1"],
    ["/code/tasks/pending/k1", "/tasks/pending/k1"],
    ["/code/pr", "/pr"],
  ])("moves %s to %s", (legacy, expected) => {
    expect(rewriteLegacyPath(legacy)).toBe(expected);
  });

  // A crafted old link must not rewrite into a protocol-relative URL, which
  // names an origin rather than a path and would leave the app.
  it.each([
    ["/website/home//evil.example/phish", "/evil.example/phish"],
    ["/website//evil.example", "/spaces//evil.example"],
  ])("keeps %s inside the app", (legacy, expected) => {
    expect(rewriteLegacyPath(legacy)).toBe(expected);
  });

  it.each(["/spaces/eng", "/inbox", "/settings/general", "/"])(
    "leaves %s alone",
    (path) => {
      expect(rewriteLegacyPath(path)).toBe(path);
    },
  );
});

describe("rewriteLegacyHref", () => {
  // Query/fragment right at a prefix boundary: rewrite the path, keep the rest
  // — a saved PR view must not divert to the `/code` → `/new` catch-all.
  it.each([
    [
      "/code/pr?prUrl=https://github.com/o/r/pull/1",
      "/pr?prUrl=https://github.com/o/r/pull/1",
    ],
    ["/code/loops/abc?edit=true", "/loops/abc?edit=true"],
    ["/code/pr#section", "/pr#section"],
    ["/website/eng/loops", "/spaces/eng/loops"],
  ])("moves %s to %s", (legacy, expected) => {
    expect(rewriteLegacyHref(legacy)).toBe(expected);
  });
});

describe("redirectFromLegacyPath", () => {
  it("lands an old link on the page it named, search and all", async () => {
    const root = createRootRoute();
    const current = createRoute({
      getParentRoute: () => root,
      path: "/spaces/$channelId/loops",
    });
    const legacy = createRoute({
      getParentRoute: () => root,
      path: "/website/$",
      beforeLoad: ({ location }) => redirectFromLegacyPath(location),
    });
    const router = createRouter({
      routeTree: root.addChildren([current, legacy]),
      history: createMemoryHistory({
        initialEntries: ["/website/eng/loops?edit=true"],
      }),
    });

    await router.load();

    expect(router.state.location.pathname).toBe("/spaces/eng/loops");
    expect(router.state.location.searchStr).toBe("?edit=true");
  });
});

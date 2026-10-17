import { describe, expect, it } from "vitest";
import {
  type PrPipelineRaw,
  queueStateFromComment,
  summarizeCi,
  toPrPipelineStatus,
} from "./pr-pipeline-status";

const CHECKBOX = `<!-- Start PR Submit Checkbox -->
- [ ] <!-- End PR Submit Checkbox -->To merge this pull request, check the box to the left or comment \`/trunk merge\` below.

After your PR is submitted to the merge queue, this comment will be automatically updated with its status. If the PR fails, failure details will also be posted here`;

function raw(overrides: Partial<NonNullable<PrPipelineRaw>> = {}) {
  return {
    state: "OPEN",
    labels: [],
    trunkComments: [],
    rollup: null,
    ...overrides,
  };
}

describe("queueStateFromComment", () => {
  it.each([
    {
      label: "a PR nobody submitted",
      body: `<!-- Trunk Merge -->\nMerging to \`main\` in this repository is managed by Trunk.\n\n${CHECKBOX}`,
      expected: null,
    },
    {
      label: "a PR submitted but not yet admitted",
      body: "<!-- Trunk Merge -->\n✨ Stack submitted to Merge by Example Person (@example). It will be added to the merge queue once all branch protection rules pass.",
      expected: "queuing",
    },
    {
      label: "a PR admitted to the queue",
      body: "<!-- Trunk Merge -->\nPull request has been added to the merge queue.",
      expected: "queued",
    },
    {
      label: "a PR under test",
      body: "<!-- Trunk Merge -->\n⏳ This pull request is being tested.",
      expected: "testing",
    },
    {
      label: "a PR the queue removed",
      body: `🚫 This pull request was removed from the merge queue because it was waiting to become mergeable for too long. Submit it again once it's ready to merge.\n${CHECKBOX}`,
      expected: "removed",
    },
    {
      label: "a PR that failed in the queue",
      body: "<!-- Trunk Merge -->\n❌ This pull request failed in the merge queue.",
      expected: "failed",
    },
    {
      label: "a merged PR",
      body: "😎 Merged successfully - [details](https://example.com).",
      expected: null,
    },
    {
      label: "a PR submitted with the checkbox",
      body: `<!-- Trunk Merge -->\nMerging to \`main\` in this repository is managed by Trunk.\n\n${CHECKBOX.replace("- [ ]", "- [x]")}`,
      expected: "queuing",
    },
  ])("reads $label", ({ body, expected }) => {
    expect(queueStateFromComment(body)).toBe(expected);
  });
});

describe("summarizeCi", () => {
  it.each([
    {
      label: "failing while other checks still run",
      checkRuns: [
        { state: "FAILURE", count: 2 },
        { state: "IN_PROGRESS", count: 3 },
        { state: "SUCCESS", count: 10 },
      ],
      expected: { state: "failing", total: 15, failed: 2, pending: 3 },
    },
    {
      label: "running when nothing failed yet",
      checkRuns: [
        { state: "QUEUED", count: 1 },
        { state: "SKIPPED", count: 4 },
      ],
      expected: { state: "running", total: 5, failed: 0, pending: 1 },
    },
    {
      label: "passing when every check settled green",
      checkRuns: [
        { state: "SUCCESS", count: 4 },
        { state: "SKIPPED", count: 2 },
      ],
      expected: { state: "passing", total: 6, failed: 0, pending: 0 },
    },
  ])("is $label", ({ checkRuns, expected }) => {
    expect(
      summarizeCi({ checkRuns, statusContexts: [], trunkChecks: [] }),
    ).toEqual(expected);
  });

  it("counts commit statuses beside check runs", () => {
    expect(
      summarizeCi({
        checkRuns: [{ state: "SUCCESS", count: 1 }],
        statusContexts: [{ state: "ERROR", count: 1 }],
        trunkChecks: [],
      })?.state,
    ).toBe("failing");
  });

  // Left in, the queue's own pending check makes green CI read as running.
  it("leaves the merge queue's own check out of CI", () => {
    expect(
      summarizeCi({
        checkRuns: [
          { state: "SUCCESS", count: 3 },
          { state: "IN_PROGRESS", count: 1 },
        ],
        statusContexts: [],
        trunkChecks: [{ status: "IN_PROGRESS", conclusion: null }],
      }),
    ).toEqual({ state: "passing", total: 3, failed: 0, pending: 0 });
  });

  it("says nothing for a commit with no checks", () => {
    expect(
      summarizeCi({ checkRuns: [], statusContexts: [], trunkChecks: [] }),
    ).toBeNull();
  });
});

describe("toPrPipelineStatus", () => {
  it("says nothing for a PR that is no longer open", () => {
    expect(
      toPrPipelineStatus(
        raw({ state: "MERGED", labels: ["trunk-merge-queue-submit"] }),
      ),
    ).toBeNull();
  });

  it("reads the submit label as queuing before Trunk writes a status", () => {
    expect(
      toPrPipelineStatus(raw({ labels: ["trunk-merge-queue-submit"] })),
    ).toEqual({ ci: null, mergeQueue: "queuing" });
  });

  it("prefers Trunk's check run over its comment", () => {
    expect(
      toPrPipelineStatus(
        raw({
          trunkComments: ["<!-- Trunk Merge -->\nStack submitted to Merge."],
          rollup: {
            checkRuns: [{ state: "IN_PROGRESS", count: 1 }],
            statusContexts: [],
            trunkChecks: [{ status: "IN_PROGRESS", conclusion: null }],
          },
        }),
      ),
    ).toEqual({ ci: null, mergeQueue: "testing" });
  });

  it("ignores Trunk's test report comment", () => {
    expect(
      toPrPipelineStatus(
        raw({
          trunkComments: [
            "<!-- Trunk Test Analytics -->\n| Failed Test | Failure Summary |",
          ],
        }),
      ),
    ).toEqual({ ci: null, mergeQueue: null });
  });
});

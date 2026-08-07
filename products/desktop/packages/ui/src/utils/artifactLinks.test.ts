import {
  findArtifactForLink,
  parseArtifactLink,
} from "@posthog/ui/utils/artifactLinks";
import { describe, expect, it } from "vitest";

const TASK_ID = "3f1c2b6a-1111-4222-8333-444455556666";
const RUN_ID = "9a8b7c6d-5555-4666-8777-888899990000";
const KEY = `posthog-tasks/artifacts/team_2/task_${TASK_ID}/run_${RUN_ID}/1a2b3c4d_report.md`;

describe("parseArtifactLink", () => {
  it.each([
    [
      "presigned url",
      `https://bucket.s3.amazonaws.com/${KEY}?X-Amz-Signature=abc`,
    ],
    [
      "path-style url with the bucket in the path",
      `https://s3.eu-west-1.amazonaws.com/ph-bucket/${KEY}`,
    ],
    [
      "percent-encoded path",
      `https://bucket.s3.amazonaws.com/${KEY.replace("report.md", "report%20final.md")}`,
    ],
  ])("reads task, run, and artifact prefix from a %s", (_label, href) => {
    const target = parseArtifactLink(href);
    expect(target?.taskId).toBe(TASK_ID);
    expect(target?.runId).toBe(RUN_ID);
    expect(target?.artifactIdPrefix).toBe("1a2b3c4d");
  });

  it.each([
    ["a non-artifact url", "https://posthog.com/docs"],
    ["a github link", "https://github.com/PostHog/posthog/issues/1"],
    [
      "an artifacts path missing the run segment",
      `https://bucket.s3.amazonaws.com/artifacts/team_2/task_${TASK_ID}/1a2b3c4d_report.md`,
    ],
    [
      "an object name without an id prefix",
      `https://bucket.s3.amazonaws.com/artifacts/team_2/task_${TASK_ID}/run_${RUN_ID}/report.md`,
    ],
    [
      "a non-http scheme",
      `posthog-code://artifacts/team_2/task_${TASK_ID}/run_${RUN_ID}/1a2b3c4d_report.md`,
    ],
    ["an unparseable href", "not a url"],
  ])("returns null for %s", (_label, href) => {
    expect(parseArtifactLink(href)).toBeNull();
  });
});

describe("findArtifactForLink", () => {
  const target = parseArtifactLink(`https://bucket.s3.amazonaws.com/${KEY}`);
  if (!target) throw new Error("fixture link must parse");

  it("matches on the exact storage path", () => {
    const artifacts = [
      { id: "0000ffff-1111-4222-8333-444455556666", storage_path: "other/key" },
      { id: "1a2b3c4d-1111-4222-8333-444455556666", storage_path: KEY },
    ];
    expect(findArtifactForLink(artifacts, target)?.storage_path).toBe(KEY);
  });

  it("falls back to the id prefix when the manifest has no storage path", () => {
    const artifacts = [{ id: "1A2B3C4D-1111-4222-8333-444455556666" }];
    expect(findArtifactForLink(artifacts, target)).toBe(artifacts[0]);
  });

  it("refuses an ambiguous id prefix rather than opening the wrong file", () => {
    const artifacts = [
      { id: "1a2b3c4d-1111-4222-8333-444455556666" },
      { id: "1a2b3c4d-9999-4222-8333-444455556666" },
    ];
    expect(findArtifactForLink(artifacts, target)).toBeNull();
  });

  it("returns null when the artifact is gone from the manifest", () => {
    expect(
      findArtifactForLink([{ id: "abcd0000", storage_path: "x" }], target),
    ).toBeNull();
  });
});

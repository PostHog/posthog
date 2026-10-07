import type {
  PrCiSummary,
  PrMergeQueueState,
  PrPipelineStatus,
} from "@posthog/shared";
import { z } from "zod";

/**
 * One GraphQL round trip for everything a list row says about an open PR. The
 * check counts come pre-aggregated from GitHub, so a PR with hundreds of checks
 * costs the same as one with three. Comments are read from both ends because
 * Trunk posts its sticky comment early and then edits it in place.
 */
export const PR_PIPELINE_STATUS_QUERY = `query PrPipelineStatus($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      state
      labels(first: 50) { nodes { name } }
      early: comments(first: 30) { nodes { author { __typename login } body } }
      recent: comments(last: 30) { nodes { author { __typename login } body } }
      commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) {
        checkRunCountsByState { state count }
        statusContextCountsByState { state count }
        nodes { __typename ... on CheckRun { name status conclusion } }
      } } } } }
    }
  }
}`;

/**
 * Narrows the GraphQL response to what the classifier reads, inside `gh`, so a
 * busy PR's comment bodies never cross the process boundary. Only Trunk's own
 * comments survive: GraphQL names the app `trunk-io` and types it `Bot`, which a
 * person cannot register.
 */
export const PR_PIPELINE_STATUS_JQ = `.data.repository.pullRequest | if . == null then null else {
  state,
  labels: [.labels.nodes[].name],
  trunkComments: [(.early.nodes + .recent.nodes)[] | select(.author.__typename == "Bot" and .author.login == "trunk-io") | .body] | unique,
  rollup: (.commits.nodes[0].commit.statusCheckRollup.contexts // null | if . == null then null else {
    checkRuns: .checkRunCountsByState,
    statusContexts: .statusContextCountsByState,
    trunkChecks: [.nodes[] | select(.__typename == "CheckRun" and (.name | startswith("Trunk Merge Queue"))) | {status, conclusion}]
  } end)
} end`;

const stateCountSchema = z.object({ state: z.string(), count: z.number() });

export const prPipelineRawSchema = z
  .object({
    state: z.string(),
    labels: z.array(z.string()),
    trunkComments: z.array(z.string()),
    rollup: z
      .object({
        checkRuns: z.array(stateCountSchema),
        statusContexts: z.array(stateCountSchema),
        trunkChecks: z.array(
          z.object({
            status: z.string().nullable(),
            conclusion: z.string().nullable(),
          }),
        ),
      })
      .nullable(),
  })
  .nullable();
export type PrPipelineRaw = z.infer<typeof prPipelineRawSchema>;

type TrunkCheck = NonNullable<
  NonNullable<PrPipelineRaw>["rollup"]
>["trunkChecks"][number];

const FAILED_CHECK_RUN_STATES = new Set([
  "FAILURE",
  "TIMED_OUT",
  "CANCELLED",
  "STARTUP_FAILURE",
  "ACTION_REQUIRED",
  "STALE",
]);
const PENDING_CHECK_RUN_STATES = new Set([
  "QUEUED",
  "IN_PROGRESS",
  "PENDING",
  "WAITING",
]);
const FAILED_STATUS_STATES = new Set(["FAILURE", "ERROR"]);
const PENDING_STATUS_STATES = new Set(["PENDING", "EXPECTED"]);

/** The rollup state GitHub counts a check run under. */
function checkRunRollupState(check: TrunkCheck): string {
  if (check.status !== "COMPLETED") return check.status ?? "PENDING";
  return check.conclusion ?? "COMPLETED";
}

export function summarizeCi(
  rollup: NonNullable<PrPipelineRaw>["rollup"],
): PrCiSummary | null {
  if (!rollup) return null;

  let total = 0;
  let failed = 0;
  let pending = 0;
  for (const { state, count } of rollup.checkRuns) {
    total += count;
    if (FAILED_CHECK_RUN_STATES.has(state)) failed += count;
    else if (PENDING_CHECK_RUN_STATES.has(state)) pending += count;
  }
  for (const { state, count } of rollup.statusContexts) {
    total += count;
    if (FAILED_STATUS_STATES.has(state)) failed += count;
    else if (PENDING_STATUS_STATES.has(state)) pending += count;
  }

  // The queue's own check is not CI: left in, a queued PR with green CI would
  // read as "running".
  for (const check of rollup.trunkChecks) {
    const state = checkRunRollupState(check);
    total -= 1;
    if (FAILED_CHECK_RUN_STATES.has(state)) failed -= 1;
    else if (PENDING_CHECK_RUN_STATES.has(state)) pending -= 1;
  }

  if (total <= 0) return null;
  const state = failed > 0 ? "failing" : pending > 0 ? "running" : "passing";
  return { state, total, failed: Math.max(failed, 0), pending };
}

/** Trunk's own check run, where the repository has it turned on. */
function queueStateFromCheck(check: TrunkCheck): PrMergeQueueState | null {
  switch (check.status) {
    case "IN_PROGRESS":
      return "testing";
    case "COMPLETED":
      switch (check.conclusion) {
        // Merged: the PR's own state carries that, so the queue says nothing.
        case "SUCCESS":
          return null;
        case "CANCELLED":
        case "SKIPPED":
        case "NEUTRAL":
        case "STALE":
          return "removed";
        default:
          return "failed";
      }
    default:
      return "queued";
  }
}

/**
 * Reads the state off Trunk's sticky comment. Only the part above the submit
 * checkbox is the status: the boilerplate under it says "If the PR fails",
 * which would otherwise read as a failure on every PR.
 */
export function queueStateFromComment(body: string): PrMergeQueueState | null {
  const [status = "", rest = ""] = body.split("<!-- Start PR Submit Checkbox");
  const text = status.replace(/<!--[\s\S]*?-->/g, "").toLowerCase();
  const checkboxSubmitted = /-\s*\[x\]/i.test(rest);

  if (/\bmerged\b/.test(text)) return null;
  if (/removed from the merge queue|cancel/.test(text)) return "removed";
  if (/fail/.test(text)) return "failed";
  if (/being tested|testing|tests passed/.test(text)) return "testing";
  if (/will be added to the merge queue|submitted|waiting/.test(text)) {
    return "queuing";
  }
  if (/added to the merge queue|in the merge queue|queued/.test(text)) {
    return "queued";
  }
  return checkboxSubmitted ? "queuing" : null;
}

const TRUNK_SUBMIT_LABEL = "trunk-merge-queue-submit";

export function mergeQueueState(
  raw: NonNullable<PrPipelineRaw>,
): PrMergeQueueState | null {
  const [check] = raw.rollup?.trunkChecks ?? [];
  if (check) return queueStateFromCheck(check);

  for (const body of raw.trunkComments) {
    if (body.includes("Trunk Test Analytics")) continue;
    if (!body.includes("Trunk Merge") && !/merge queue/i.test(body)) continue;
    const state = queueStateFromComment(body);
    if (state) return state;
  }

  // Trunk adds the label as soon as a PR is submitted, before it writes any
  // status, so the label alone means "on its way in".
  return raw.labels.includes(TRUNK_SUBMIT_LABEL) ? "queuing" : null;
}

export function toPrPipelineStatus(
  raw: PrPipelineRaw,
): PrPipelineStatus | null {
  // A merged or closed PR has nothing left to run or queue.
  if (!raw || raw.state !== "OPEN") return null;
  return { ci: summarizeCi(raw.rollup), mergeQueue: mergeQueueState(raw) };
}

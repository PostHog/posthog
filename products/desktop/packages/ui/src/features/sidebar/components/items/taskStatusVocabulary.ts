import {
  ArrowSquareIn,
  GitBranch,
  GitMerge,
  GitPullRequest,
  type Icon,
  Laptop,
} from "@phosphor-icons/react";
import {
  getOriginProductMeta,
  type TaskIconProps,
} from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";

/**
 * The task state a status dot / badge stack is drawn from: what the shipped
 * `TaskIcon` takes, plus the PR's url.
 *
 * The url matters separately from `prState` because it arrives much earlier. A
 * cloud run writes `latest_run.output.pr_url` the moment it opens the PR, while
 * `prState` needs a GitHub lookup that a cloud-only task may never get. So the
 * url answers "is there a PR" and the state answers "what happened to it" — and
 * a row can say the first without waiting on the second.
 */
export type TaskStatusInput = TaskIconProps & {
  prUrl?: string | null;
};

/**
 * The status vocabulary for a task row. It splits what `TaskIcon` crams into one
 * glyph, and each half only speaks when it has something to say:
 *
 *   - the **dot** on the left is attention and activity ONLY — is this blocked
 *     on me, working, or waiting to be read? Everything settled shares one
 *     quiet hollow dot;
 *   - the **badges** on the right are identity — where it came from, whether
 *     it's cloud, and what came out of it. The PR badge carries its own colour,
 *     so PR state never needs to spend the dot.
 *
 * That split is the whole point: a merged PR from Slack reads as "nothing owed"
 * (hollow dot) with a purple merge badge and a source badge, instead of
 * `TaskIcon`'s single glyph where the winning state hides the other two.
 */

export type DotTone = "green" | "purple" | "yellow" | "red" | "blue" | "gray";

/**
 * Radix step 9 — the "solid" step, the only one meant to be a filled fill.
 * Yellow is the exception: it's the brand's `--primary` (yellow in dark, orange
 * in light), the same token the unread badges use, so "something is owed to you"
 * is one colour across the window rather than two shades of amber.
 */
export const DOT_TONE_VAR: Record<DotTone, string> = {
  green: "var(--green-9)",
  purple: "var(--purple-9)",
  yellow: "var(--primary)",
  red: "var(--red-9)",
  blue: "var(--blue-9)",
  gray: "var(--muted-foreground)",
};

/**
 * Step 11 — the readable step, for a glyph rather than a filled shape. Grey is
 * the exception at step 10: it's there to read as *mid* grey, present but
 * plainly not asking for anything, which step 11 is too emphatic for. Yellow is
 * `--primary` here too — it has no scale of its own, and the token is already
 * chosen to read against either theme's chrome.
 */
export const TONE_ICON_VAR: Record<DotTone, string> = {
  green: "var(--green-11)",
  purple: "var(--purple-11)",
  yellow: "var(--primary)",
  red: "var(--red-11)",
  blue: "var(--blue-11)",
  gray: "var(--gray-10)",
};

export interface TaskDot {
  tone: DotTone;
  /** Filled = live signal; hollow = settled, nothing owed to you. */
  style: "solid" | "hollow";
  /** Flashing = happening now, or wanting you now. */
  pulse: boolean;
  /**
   * Draw as the braille dots spinner instead of one dot — still dot-shaped, so
   * it stays in the dot column's vocabulary, but the motion is a *cycle* rather
   * than a blink, which is the honest shape for "output is arriving".
   */
  spinner?: boolean;
  /**
   * Draw the dot barely there. For states that are deliberately inert — the task
   * isn't idle waiting for you, it's been *put down* — so the row should read as
   * present but skippable rather than joining the quiet-but-live majority.
   */
  faint?: boolean;
  label: string;
}

/**
 * State → dot. Three things only: blue wants a decision from you, the brand
 * yellow is working or unread, grey is quiet.
 *
 * Run mechanics are deliberately absent. A cloud run is magic from the outside —
 * queued, claiming a sandbox, retrying, and erroring out are our problems, not
 * the reader's, and a list that reports them turns every infrastructure hiccup
 * into a red mark on the reader's work. So a failed run is not a state here: what
 * the reader actually gets is output they haven't seen, which is `isUnread`, and
 * the run's real story lives in the task detail where there's room to tell it.
 *
 * A cloud run's queued is folded into working for the same reason. "Waiting on a
 * sandbox" and "a sandbox is writing code" are one fact to the reader, that it's
 * under way, so they share the spinner. Two states don't share it: a local run
 * at `queued`, whose persisted status nothing ever advances, and a run at
 * `in_progress` with nothing streaming. Both claims outlive the work, and a
 * spinner that never stops is a lie about the machine.
 *
 * And a run that has already opened a PR is not working, whatever its status
 * says. The cloud workflow keeps the run `in_progress` while it babysits CI
 * after opening the PR, and under a merge queue that wait ends only when someone
 * enqueues the merge — so the run can claim to be working for hours after the
 * agent stopped. The PR is the deliverable; once it exists the badge carries the
 * story and the dot goes quiet. This beats a status that merely claims work, not
 * one that is visibly starting: a re-queued cloud run keeps its spinner even
 * with last run's PR still on the task.
 */
export function taskDot(props: TaskStatusInput): TaskDot {
  if (props.needsPermission) {
    // Not flashing. Blue already reads as the one thing in the list that is
    // yours to answer, and a blink on top of that argues with every quiet row
    // around it — in a sidebar of a dozen spaces it is the whole tree moving.
    return {
      tone: "blue",
      style: "solid",
      pulse: false,
      // What the agent is asking for varies: permission to run a tool, an
      // answer to a question it asked with one. Both reach the reader as the
      // same prompt in the same place, so the row names the ask rather than the
      // mechanism behind it.
      label: "Needs your input",
    };
  }
  // Spinning means something is moving on its own: a prompt in flight, or a
  // cloud run still coming up. Cloud `queued` is a sandbox being claimed, and
  // the backend leaves that state by itself, so the motion is bounded. A local
  // run at `queued` is not a launch: nothing advances a local run's persisted
  // status, so it can sit there for hours after the agent is done with it.
  const isStartingCloudRun =
    props.taskRunStatus === "queued" && props.workspaceMode === "cloud";
  if (props.isGenerating || isStartingCloudRun) {
    return {
      tone: "yellow",
      style: "solid",
      pulse: false,
      spinner: true,
      label: props.isGenerating ? "Working" : "Starting",
    };
  }
  // Only a background run's status is a claim about work. An interactive run is
  // left `in_progress` after it succeeds, deliberately — the session stays open
  // for a follow-up, so the status says "followable", not "working". Reading it
  // as a claim marked every finished session as pending, on a row nobody could
  // clear: opening the session writes a viewed timestamp, not a status.
  const runClaimsWork =
    props.runMode === "background" &&
    (props.taskRunStatus === "in_progress" || props.taskRunStatus === "queued");
  if (runClaimsWork && !hasPullRequest(props)) {
    return {
      tone: "yellow",
      style: "solid",
      pulse: false,
      label: "Pending — no work in flight",
    };
  }
  if (props.isUnread) {
    // Solid, not flashing: fresh output is worth a look but isn't blocking the
    // run the way a permission prompt is, and two moving states in one list
    // cancel each other out.
    return {
      tone: "yellow",
      style: "solid",
      pulse: false,
      label: "Unread — something to read",
    };
  }
  if (props.isSuspended) {
    return {
      tone: "gray",
      style: "hollow",
      pulse: false,
      faint: true,
      label: "Suspended — parked",
    };
  }
  return {
    tone: "gray",
    style: "hollow",
    pulse: false,
    label: "All caught up",
  };
}

/**
 * Whether a PR exists at all, by either route: the state from a GitHub lookup,
 * or just the url the run wrote when it opened one.
 */
function hasPullRequest(props: TaskStatusInput): boolean {
  return props.prState != null || !!props.prUrl;
}

export interface TaskBadge {
  key: string;
  Icon: Icon;
  label: string;
  /** Set only where colour earns its keep — currently PR state. */
  tone?: DotTone;
  /**
   * Where the badge points, for the surfaces that can offer it. A row can't:
   * it is a `<button>`, so its badges stay spans. The hover card is not, so it
   * draws a badge with a url as something you can click through to — the PR, or
   * the Slack thread the task was filed from.
   */
  url?: string;
}

/**
 * The PR the task opened, if it has one. Merged / ready / closed is the outcome
 * people actually scan a task list for, and it is a three-value vocabulary on a
 * glyph that already means "pull request", so this is the one badge with
 * colour.
 */
function pullRequestBadge(
  props: TaskStatusInput,
  hideResolved: boolean,
): TaskBadge | null {
  const prUrl = props.prUrl ?? undefined;
  // A surface that draws PR state itself only draws it once the state has
  // resolved, so the url-only badge below still has to speak for the window
  // before that — and for the lookups that never resolve at all.
  if (hideResolved && props.prState != null) return null;
  if (props.prState === "merged") {
    return {
      key: "pr",
      Icon: GitMerge,
      label: "Merged",
      tone: "purple",
      url: prUrl,
    };
  }
  if (props.prState === "open") {
    return {
      key: "pr",
      Icon: GitPullRequest,
      label: "PR ready for review",
      tone: "green",
      url: prUrl,
    };
  }
  if (props.prState === "closed") {
    return {
      key: "pr",
      Icon: GitPullRequest,
      label: "PR closed unmerged",
      tone: "red",
      url: prUrl,
    };
  }
  if (props.prState === "draft") {
    // Mid grey: a draft is a real PR, so it earns a solid glyph, but it isn't
    // asking for anything yet — grey is the "exists, no verdict" slot.
    return {
      key: "pr",
      Icon: GitPullRequest,
      label: "Draft PR",
      tone: "gray",
      url: prUrl,
    };
  }
  if (props.prUrl) {
    // A PR we know exists but haven't resolved the state of. Uncoloured on
    // purpose: colour here is a verdict, and inventing one would be worse than
    // saying "there's a PR, go look". Showing the badge is not optional — a
    // task that opened a PR and shows no sign of it reads as having done
    // nothing.
    return {
      key: "pr",
      Icon: GitPullRequest,
      label: "Pull request",
      url: props.prUrl,
    };
  }
  return null;
}

/**
 * Identity → badges, widest context first so the stack reads left-to-right as
 * "who asked, where it runs, what came out of it".
 *
 * Only the local case says where it runs. Running in the cloud is what a task
 * does by default, and a badge on the majority of rows is a badge nobody reads —
 * so cloud is silent and the laptop marks the exception. A cloud row with
 * nothing else to say carries no badges at all, which is the honest shape:
 * nothing has happened to it yet.
 *
 * Origins share ONE glyph, with Slack as the exception. Eight product marks at
 * avatar size is a vocabulary nobody learns — and the badge's job in a nav row
 * is "this didn't come from you", which is the same fact whether Slack or error
 * tracking filed it. The tooltip names the actual product for anyone who needs
 * it. Slack keeps its own mark because it's the one origin where the row came
 * from a person in a thread, and readers already know that logo on sight.
 *
 * The PR badge is the exception that gets colour, and lives in
 * {@link pullRequestBadge}.
 */
export function taskBadges(
  props: TaskStatusInput,
  {
    /**
     * Off where the surface draws PR state itself — the session header, whose
     * git control sits at the end of the same row. Only the states that
     * control renders are dropped.
     */
    includePr = true,
  }: { includePr?: boolean } = {},
): TaskBadge[] {
  const badges: TaskBadge[] = [];
  const origin = getOriginProductMeta(props.originProduct);
  const isSlack = props.originProduct === "slack";
  if (origin) {
    badges.push({
      key: "origin",
      Icon: isSlack ? SlackMark : ArrowSquareIn,
      label: `Source: ${origin.label}`,
      // Slack is the one origin that hands back a place to go: the thread the
      // task was filed from. Other products name themselves and stop there.
      url: isSlack ? (props.slackThreadUrl ?? undefined) : undefined,
    });
  }
  // Asking here rather than filtering the result keeps the rest of the stack
  // intact: a filtered list loses the "Local" badge, which only appears when
  // nothing else does.
  const pr = pullRequestBadge(props, !includePr);
  if (pr) {
    badges.push(pr);
  } else if (props.hasDiff) {
    badges.push({
      key: "branch",
      Icon: GitBranch,
      label: "Has changes",
      tone: "yellow",
    });
  }
  // Only when we actually know it runs on this machine. An unset mode is
  // unknown, not local, and claiming a laptop for it would be a guess.
  const runsLocally =
    props.workspaceMode === "local" || props.workspaceMode === "worktree";
  if (badges.length === 0 && runsLocally) {
    badges.push({ key: "local", Icon: Laptop, label: "Local" });
  }
  return badges;
}

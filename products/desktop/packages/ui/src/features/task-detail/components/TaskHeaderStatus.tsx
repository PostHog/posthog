import { PushPin } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { WorkspaceMode } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskStatusInput } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import {
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskBadge,
  type TaskStatusInput,
  TONE_ICON_VAR,
  taskBadges,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { WorkspaceModeBadge } from "@posthog/ui/features/task-detail/components/WorkspaceModeBadge";
import { toast } from "@posthog/ui/primitives/toast";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactElement, type ReactNode, useState } from "react";

// What quill's `icon-sm` button renders a glyph at. The marks that aren't
// buttons take it too, so a row of them doesn't change glyph size halfway.
const ICON_SIZE = 12;

/**
 * The session's state for the window header, or `null` where the header keeps
 * its old workspace-mode glyph — outside project-bluebird, and before the
 * task's state has landed.
 */
function useHeaderStatus(task: Task): TaskStatusInput | null {
  const bluebird = useBluebirdFlag();
  // The PR lookup is the one part that reaches the host, so it goes no further
  // than the surface that draws it.
  const status = useTaskStatusInput(task, { withPrStatus: bluebird });
  return bluebird ? status : null;
}

/**
 * The header's marks are the space list's, so a session reads the same open in
 * front of you as it does in the list you opened it from. `no-drag` because the
 * header is a window drag region, and a mark whose tooltip never opens is a
 * mark that says nothing.
 */
function HeaderMarks({ children }: { children: ReactNode }) {
  return (
    <TaskStatusTooltips>
      <span className="no-drag flex shrink-0 items-center">{children}</span>
    </TaskStatusTooltips>
  );
}

/**
 * A label-only tooltip, opening below because the header is the top of the
 * window. `disableHoverablePopup` and `pointer-events-none` for the reason the
 * space list's tooltips take them: a popup the pointer can hold open sits over
 * what it describes.
 */
function MarkTooltip({
  label,
  children,
}: {
  label: string;
  children: ReactElement;
}) {
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger render={children} />
      <TooltipContent side="bottom" className="pointer-events-none select-none">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A header mark you can press, drawn as the header's own icon button so unpin
 * and "open the thread" look like the copy-link button beside them rather than
 * like the list's avatars.
 */
function HeaderButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <MarkTooltip label={label}>
      <Button
        size="icon-sm"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
      >
        {children}
      </Button>
    </MarkTooltip>
  );
}

/**
 * The mark before the session's title in the window header: its state dot,
 * whose tooltip names the state in the same words the space list uses.
 *
 * It replaces the cloud / laptop / worktree glyph, which said where the run
 * lives and nothing about whether it wants anything from you. Where the run
 * lives moves to {@link TaskHeaderActions}, and in that vocabulary the cloud is
 * silent: running there is what a session does by default, so only the local
 * exception earns a badge.
 */
export function TaskHeaderMark({
  task,
  mode,
  checkoutPath,
}: {
  task: Task;
  mode?: WorkspaceMode;
  /** Directory the task runs in, for the workspace-mode glyph's tooltip. */
  checkoutPath?: string | null;
}) {
  const status = useHeaderStatus(task);
  if (!status) {
    return <WorkspaceModeBadge mode={mode} checkoutPath={checkoutPath} />;
  }
  return (
    <HeaderMarks>
      <TaskStatusDot dot={taskDot(status)} />
    </HeaderMarks>
  );
}

/**
 * The pin, as the control it names. In the space list the pin is a badge on a
 * row that can't hold controls; the header is one line about one session, so
 * the mark that says "you put this here" is also how you put it there and take
 * it back.
 *
 * Drawn whether or not the session is pinned, because a control that vanishes
 * once used can only be undone from somewhere else. Unpinned it is an outline
 * in the button's own colour, so it reads as an offer rather than a fact about
 * the session.
 */
function HeaderPinButton({
  taskId,
  pinned,
}: {
  taskId: string;
  pinned: boolean;
}) {
  const { togglePin } = usePinnedTasks();
  const [toggling, setToggling] = useState(false);
  return (
    <HeaderButton
      label={pinned ? "Unpin" : "Pin"}
      disabled={toggling}
      onClick={() => {
        setToggling(true);
        togglePin(taskId)
          .then(() => toast.success(pinned ? "Unpinned" : "Pinned"))
          .catch((error: unknown) =>
            toast.error(pinned ? "Couldn't unpin" : "Couldn't pin", {
              description:
                error instanceof Error ? error.message : String(error),
            }),
          )
          .finally(() => setToggling(false));
      }}
    >
      {/* Pinned is the one colour here, and it's the list's choice: amber says
          "you put this here" without joining the states that are asking for
          something. Unpinned takes the button's own colour, so the offer looks
          like the copy-link button next to it rather than a mark. */}
      <PushPin
        size={ICON_SIZE}
        weight={pinned ? "fill" : "regular"}
        className={pinned ? "text-primary" : undefined}
      />
    </HeaderButton>
  );
}

/**
 * One of the session's badges. A badge that points somewhere — the Slack thread
 * it was filed from, the PR it opened — is a button that goes there. The rest
 * state a fact about the session, so they stay plain marks with the same
 * tooltip rather than buttons whose hover promises a click that does nothing.
 */
function HeaderBadge({
  badge: { Icon, label, tone, url },
}: {
  badge: TaskBadge;
}) {
  function glyph(muted: boolean) {
    return (
      // An explicit `color` (an SVG fill) rather than a text-* class where the
      // vocabulary sets a tone, the same way the list's badges are drawn.
      <Icon
        aria-hidden
        size={ICON_SIZE}
        weight={tone ? "fill" : "regular"}
        color={tone ? TONE_ICON_VAR[tone] : undefined}
        className={!tone && muted ? "text-muted-foreground" : undefined}
      />
    );
  }
  if (!url) {
    return (
      <MarkTooltip label={label}>
        {/* Dimmer than the buttons beside it, and sized to their box so a row of
            marks doesn't step as badges come and go. A mark you can't press
            shouldn't look like one you can. */}
        <span
          aria-label={label}
          role="img"
          className="flex size-6 shrink-0 items-center justify-center"
        >
          {glyph(true)}
        </span>
      </MarkTooltip>
    );
  }
  return (
    <HeaderButton label={label} onClick={() => openExternalUrl(url)}>
      {glyph(false)}
    </HeaderButton>
  );
}

/**
 * What rides after the title: unpin, open the Slack thread, open the PR, and
 * the badges that only have something to say.
 *
 * Drawn as the header's own icon buttons rather than the space list's stacked
 * avatars. A list row is a `<button>`, so its badges can only ever be marks; the
 * header is one line about one session sitting next to a live copy-link button,
 * and beside it a stack of overlapping avatars reads as decoration.
 *
 * Nothing at all when there is nothing to say, rather than an empty group whose
 * padding still moves the title's neighbours.
 */
export function TaskHeaderActions({ task }: { task: Task }) {
  const status = useHeaderStatus(task);
  if (!status) return null;
  return (
    <HeaderMarks>
      <HeaderPinButton taskId={task.id} pinned={!!status.isPinned} />
      {taskBadges(status)
        // The PR is the one badge the header drops: the git control at the end
        // of the same row already draws the PR, in colour, with its actions
        // behind it. Two marks for one PR a hand's width apart is one too many.
        .filter((badge) => badge.key !== "pr")
        .map((badge) => (
          <HeaderBadge key={badge.key} badge={badge} />
        ))}
    </HeaderMarks>
  );
}

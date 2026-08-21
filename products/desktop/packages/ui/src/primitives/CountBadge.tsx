import { cn } from "@posthog/quill";

/**
 * Unread counts read in the brand's primary — yellow in dark, orange in light —
 * so a badge is the app's own colour rather than a warning. Red is reserved for
 * failure. Ambient "how much is parked here" counts stay grey.
 */
export type CountBadgeTone = "notification" | "neutral";

interface CountBadgeProps {
  count: number;
  tone?: CountBadgeTone;
  className?: string;
  title?: string;
}

function formatCount(count: number): string {
  if (count > 99) return "99+";
  return String(count);
}

function countBadgeSizeClass(label: string): string {
  return label.length > 1
    ? "h-[18px] min-w-[18px] shrink-0 px-1"
    : "h-[18px] w-[18px] shrink-0";
}

const TONE_CLASS: Record<CountBadgeTone, string> = {
  notification: "bg-primary text-primary-foreground",
  // Theme tokens, not the absolute gray scale: these sit on chrome whose
  // lightness relationship to gray-N inverts between light and dark.
  neutral: "bg-muted text-muted-foreground",
};

/**
 * A count pill. The one place the 99+ cap and the hide-at-zero rule live —
 * every badge that reimplemented them drifted on one or the other.
 *
 * Size and position come through `className` (tailwind-merge lets callers
 * override the defaults), because the surfaces genuinely differ: a nav icon
 * overlay is not the same shape as a sidebar row's trailing count.
 */
export function CountBadge({
  count,
  tone = "notification",
  className,
  title,
}: CountBadgeProps) {
  if (count <= 0) return null;
  const label = formatCount(count);

  return (
    <span
      className={cn(
        countBadgeSizeClass(label),
        "inline-flex items-center justify-center rounded-full font-medium text-[10px] tabular-nums leading-none",
        TONE_CLASS[tone],
        className,
      )}
      title={title}
    >
      {label}
    </span>
  );
}

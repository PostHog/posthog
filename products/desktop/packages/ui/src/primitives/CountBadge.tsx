import { cn } from "@posthog/quill";

interface CountBadgeProps {
  count: number;
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

export function CountBadge({ count, className, title }: CountBadgeProps) {
  const label = formatCount(count);

  return (
    <span
      className={cn(
        countBadgeSizeClass(label),
        "inline-flex items-center justify-center rounded-full bg-(--red-9) font-medium text-(--gray-contrast) text-[10px] tabular-nums leading-none",
        className,
      )}
      title={title}
    >
      {label}
    </span>
  );
}

import { formatRelativeTimeLong } from "@posthog/shared";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Text } from "@radix-ui/themes";

interface RelativeTimestampProps {
  timestamp: string | number | Date | null | undefined;
  className?: string;
}

export function RelativeTimestamp({
  timestamp,
  className,
}: RelativeTimestampProps) {
  const date =
    timestamp instanceof Date
      ? timestamp
      : timestamp !== null && timestamp !== undefined
        ? new Date(timestamp)
        : null;

  if (date === null || Number.isNaN(date.getTime())) {
    return null;
  }

  return (
    <Tooltip content={date.toLocaleString()}>
      <Text
        className={`shrink-0 text-(--gray-10) text-[11px] ${className ?? ""}`}
      >
        {formatRelativeTimeLong(date.getTime())}
      </Text>
    </Tooltip>
  );
}

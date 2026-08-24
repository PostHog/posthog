import { Text } from "@posthog/quill";
import type { ReactNode } from "react";

export function Section({
  title,
  trailing,
  children,
}: {
  title: string;
  trailing?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 px-0.5">
        <Text className="font-semibold text-[10px] text-muted-foreground uppercase tracking-wider">
          {title}
        </Text>
        {trailing}
      </div>
      <div className="rounded-(--radius-3) border border-border bg-card px-2.5">
        {children}
      </div>
    </div>
  );
}

export function Row({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-8 items-center justify-between gap-2 border-border border-b py-1 last:border-b-0">
      <Text className="text-[12px] text-muted-foreground">{label}</Text>
      {children}
    </div>
  );
}

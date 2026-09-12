import { Text } from "@posthog/quill";
import type { ReactNode } from "react";

/**
 * One block of the share dialog: a heading, an optional control on the same
 * line (the public toggle), one line saying who the link is for, then the rows.
 */
export function ShareSection({
  title,
  control,
  description,
  children,
}: {
  title: ReactNode;
  control?: ReactNode;
  description: string;
  children?: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <Text size="sm" weight="medium">
          {title}
        </Text>
        {control}
      </div>
      <Text size="xs" variant="muted">
        {description}
      </Text>
      {children}
    </section>
  );
}

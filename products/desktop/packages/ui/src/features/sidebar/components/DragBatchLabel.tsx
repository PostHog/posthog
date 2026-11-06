import { sessionsLabel } from "@posthog/core/sidebar/selection";
import type { ReactElement } from "react";

/** What a drag preview says in place of a row once it carries a whole batch. */
export function DragBatchLabel({ count }: { count: number }): ReactElement {
  return (
    <div className="px-3 py-2 font-medium text-[13px]">
      Moving {sessionsLabel(count)}
    </div>
  );
}

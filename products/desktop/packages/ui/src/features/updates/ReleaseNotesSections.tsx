import { Text } from "@posthog/quill";
import type { CategorizedNotes } from "@posthog/ui/features/updates/releaseNotes";
import type { ReactElement } from "react";

function ReleaseSection({
  title,
  items,
}: {
  title: string;
  items: string[];
}): ReactElement | null {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <Text
        render={<span />}
        size="xxs"
        weight="medium"
        variant="muted"
        className="uppercase tracking-wide"
      >
        {title}
      </Text>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {items.map((item) => (
          <li
            key={`${title}-${item}`}
            className="flex gap-2 text-foreground text-xs leading-relaxed"
          >
            <span className="mt-px select-none text-muted-foreground">•</span>
            <span className="min-w-0">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReleaseNotesSections({
  notes,
}: {
  notes: CategorizedNotes;
}): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <ReleaseSection title="Improved" items={notes.improved} />
      <ReleaseSection title="Fixed" items={notes.fixed} />
    </div>
  );
}

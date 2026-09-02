import type { CategorizedNotes } from "@posthog/ui/features/updates/releaseNotes";
import { Flex } from "@radix-ui/themes";

function ReleaseSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Flex direction="column" gap="1">
      <span className="font-medium text-[11px] text-gray-10 uppercase tracking-wide">
        {title}
      </span>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {items.map((item) => (
          <li
            key={`${title}-${item}`}
            className="flex gap-2 text-[13px] text-gray-12 leading-relaxed"
          >
            <span className="mt-px select-none text-gray-9">•</span>
            <span className="min-w-0">{item}</span>
          </li>
        ))}
      </ul>
    </Flex>
  );
}

export function ReleaseNotesSections({ notes }: { notes: CategorizedNotes }) {
  return (
    <Flex direction="column" gap="3">
      <ReleaseSection title="Improved" items={notes.improved} />
      <ReleaseSection title="Fixed" items={notes.fixed} />
    </Flex>
  );
}

import { Skeleton } from "@posthog/quill";

export function SkillListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      {Array.from({ length: rows }, (_, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length placeholder
          key={index}
          className="flex items-center gap-2 rounded-md border border-transparent px-2 py-1"
        >
          <Skeleton className="size-5 shrink-0 rounded" />
          <Skeleton
            className="h-3 rounded"
            style={{ width: `${[110, 90, 140, 120][index % 4]}px` }}
          />
          <Skeleton
            className="h-3 min-w-0 flex-1 rounded"
            style={{ maxWidth: `${[420, 300, 520, 360][index % 4]}px` }}
          />
        </div>
      ))}
    </div>
  );
}

export function SkillBodySkeleton() {
  return (
    <div className="flex flex-col gap-4 px-3 py-2.5">
      {[3, 4, 2].map((lines, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length placeholder
          key={index}
          className="flex flex-col gap-2"
        >
          <Skeleton className="h-3.5 w-32 rounded" />
          {Array.from({ length: lines }, (_, line) => (
            <Skeleton
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length placeholder
              key={line}
              className="h-2.5 rounded"
              style={{ width: line === lines - 1 ? "62%" : "100%" }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

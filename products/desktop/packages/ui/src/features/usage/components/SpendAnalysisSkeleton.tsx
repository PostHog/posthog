import { Skeleton } from "@posthog/quill";
import { Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

const SKELETON_ROWS = ["first", "second", "third", "fourth", "fifth"];
const SKELETON_MODELS = [
  "first",
  "second",
  "third",
  "fourth",
  "fifth",
  "sixth",
];
const SKELETON_CHART_BARS = [28, 45, 62, 36, 70, 52, 84, 41, 58, 74];

function SpendKpiSkeleton() {
  return (
    <div className="grid grid-cols-4 overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)">
      {SKELETON_ROWS.slice(0, 4).map((key, index) => (
        <div
          key={key}
          className={`flex min-w-0 flex-col gap-3 px-4 py-3 ${index === 3 ? "" : "border-(--gray-5) border-r"}`}
        >
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-3 w-24" />
        </div>
      ))}
    </div>
  );
}

function SpendTableSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-4">
        <Skeleton className="h-3 w-12" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
      </div>
      {SKELETON_ROWS.map((key) => (
        <div key={key} className="grid grid-cols-4 gap-4">
          <Skeleton className="h-3 w-4/5" />
          <Skeleton className="h-3 w-3/5" />
          <Skeleton className="h-3 w-3/5" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}

export function SpendAnalysisSkeleton() {
  return (
    <>
      <SpendKpiSkeleton />
      <SpendOverTimeCardSkeleton />
      <UsageCardSkeleton title="Cost by model">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {SKELETON_MODELS.map((key) => (
            <div
              key={key}
              className="flex flex-col gap-3 rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2) p-3"
            >
              <div className="flex items-center justify-between gap-4">
                <Skeleton className="h-4 w-3/5" />
                <Skeleton className="h-4 w-10" />
              </div>
              <Skeleton className="h-3 w-full" />
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-full" />
              </div>
            </div>
          ))}
        </div>
      </UsageCardSkeleton>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <UsageCardSkeleton title="By tool">
          <SpendTableSkeleton />
        </UsageCardSkeleton>
        <UsageCardSkeleton title="By product">
          <SpendTableSkeleton />
        </UsageCardSkeleton>
      </div>
      <UsageCardSkeleton title="Where to look">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
          <Skeleton className="h-3 w-3/5" />
          <div className="border-(--gray-5) border-t pt-3">
            <Skeleton className="h-7 w-64" />
          </div>
        </div>
      </UsageCardSkeleton>
    </>
  );
}

function SpendOverTimeCardSkeleton() {
  return (
    <UsageCardSkeleton title="Daily spend and total">
      <div className="flex h-56 items-end gap-2 px-3 pt-6">
        {SKELETON_CHART_BARS.map((height) => (
          <Skeleton
            key={height}
            className="flex-1"
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
    </UsageCardSkeleton>
  );
}

function UsageCardSkeleton({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) p-4">
      <Text className="font-medium text-sm">{title}</Text>
      {children}
    </div>
  );
}

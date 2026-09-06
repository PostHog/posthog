import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";

/** An underlined tab strip where a tab may carry a count beside its label. */
export function CountedTabStrip<T extends string>({
  tabs,
  value,
  counts,
  onValueChange,
  dataAttrPrefix,
  className,
}: {
  tabs: readonly { key: T; label: string }[];
  value: T;
  /** A count is shown only when it is above zero. */
  counts?: Partial<Record<T, number>>;
  onValueChange: (tab: T) => void;
  dataAttrPrefix: string;
  className?: string;
}) {
  return (
    <Tabs
      value={value}
      className={className}
      onValueChange={(next: string) => onValueChange(next as T)}
    >
      <TabsList variant="line" className="h-auto gap-0.5">
        {tabs.map(({ key, label }) => {
          const count = counts?.[key];
          return (
            <TabsTrigger
              key={key}
              value={key}
              className="gap-1.5 px-2.5 py-2"
              data-attr={`${dataAttrPrefix}-${key}`}
            >
              <span className="font-medium text-[13px]">{label}</span>
              {count !== undefined && count > 0 ? (
                <span className="text-[12px] text-gray-10 tabular-nums">
                  {count}
                </span>
              ) : null}
            </TabsTrigger>
          );
        })}
      </TabsList>
    </Tabs>
  );
}

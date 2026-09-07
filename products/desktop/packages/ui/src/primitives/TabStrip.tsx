import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";

/** An underlined tab strip, on the design system's own sizing. */
export function TabStrip<T extends string>({
  tabs,
  value,
  onValueChange,
  dataAttrPrefix,
  className,
}: {
  tabs: readonly { key: T; label: string }[];
  value: T;
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
      <TabsList variant="line">
        {tabs.map(({ key, label }) => (
          <TabsTrigger
            key={key}
            value={key}
            data-attr={`${dataAttrPrefix}-${key}`}
          >
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

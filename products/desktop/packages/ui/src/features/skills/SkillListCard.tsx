import type { ReactNode, Ref } from "react";

interface SkillListCardProps {
  /** Forwarded to the row element (e.g. for scroll-into-view). */
  cardRef?: Ref<HTMLDivElement>;
  icon: ReactNode;
  iconClass?: string;
  title: string;
  subtitle?: string;
  isSelected: boolean;
  dimmed?: boolean;
  onClick: () => void;
  /** Badges or counts rendered after the text block. */
  trailing?: ReactNode;
}

export function SkillListCard({
  cardRef,
  icon,
  iconClass,
  title,
  subtitle,
  isSelected,
  dimmed,
  onClick,
  trailing,
}: SkillListCardProps) {
  return (
    <div
      ref={cardRef}
      className={`flex items-center gap-2 rounded-md border px-2 py-1 transition-colors ${
        isSelected
          ? "border-accent-8 bg-accent-3"
          : "border-transparent hover:border-gray-5 hover:bg-gray-3"
      }`}
    >
      <button
        type="button"
        className={`flex min-w-0 flex-1 cursor-pointer items-baseline gap-2 text-left ${dimmed ? "opacity-40" : ""}`}
        onClick={onClick}
      >
        <span
          className={`flex size-5 shrink-0 translate-y-0.5 items-center justify-center rounded ${iconClass ?? "bg-gray-4 text-gray-11"}`}
        >
          {icon}
        </span>
        <span className="min-w-0 max-w-[55%] truncate font-medium text-[13px] text-gray-12">
          {title}
        </span>
        {subtitle ? (
          <span className="min-w-0 flex-1 truncate text-[12px] text-gray-10">
            {subtitle}
          </span>
        ) : null}
      </button>

      {trailing}
    </div>
  );
}

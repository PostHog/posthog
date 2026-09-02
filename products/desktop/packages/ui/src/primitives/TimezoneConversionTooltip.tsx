import {
  Check,
  Copy,
  Globe,
  House,
  Laptop,
  Terminal,
} from "@phosphor-icons/react";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { type ReactNode, useRef, useState } from "react";
import {
  formatTimestampInTimezone,
  formatTimezoneAbbreviation,
  systemTimezone,
} from "./timezone";
import { useCopy } from "./useCopy";

interface TimezoneConversionTooltipProps {
  timestamp: string | number | Date;
  timezone: string;
  timezoneLabel?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
}

interface ConversionRowProps {
  abbreviation: string;
  icon: typeof Laptop;
  label: string;
  value: string;
}

function ConversionRow({
  abbreviation,
  icon: Icon,
  label,
  value,
}: ConversionRowProps) {
  const { copied, copy } = useCopy(1500);

  return (
    <div className="contents">
      <Icon size={15} className="text-gray-11" />
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 font-medium text-sm">{label}</span>
        {abbreviation ? (
          <span className="truncate text-muted-foreground text-sm">
            {abbreviation}
          </span>
        ) : null}
      </span>
      <span className="whitespace-nowrap text-right text-muted-foreground text-sm">
        {value}
      </span>
      <Button
        variant="link-muted"
        size="icon-xs"
        aria-label={copied ? `${label} time copied` : `Copy ${label} time`}
        className="rounded p-0.5 text-gray-10 hover:bg-gray-4 hover:text-gray-12"
        onClick={() => copy(value)}
      >
        {copied ? (
          <Check size={13} className="text-green-11" />
        ) : (
          <Copy size={13} />
        )}
      </Button>
    </div>
  );
}

export function TimezoneConversionTooltip({
  timestamp,
  timezone,
  timezoneLabel = "Schedule",
  children,
  defaultOpen = false,
  open: controlledOpen,
}: TimezoneConversionTooltipProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const open = controlledOpen ?? internalOpen;
  const portalContainer =
    typeof document === "undefined"
      ? null
      : document.getElementById("portal-container");
  const closeTimer = useRef<number | null>(null);
  const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return children;

  const keepOpen = () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    if (controlledOpen === undefined) setInternalOpen(true);
  };

  const scheduleClose = () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => {
      if (controlledOpen === undefined) setInternalOpen(false);
    }, 150);
  };

  const deviceTimezone = systemTimezone();
  const rows = [
    {
      label: "Your device",
      timezone: deviceTimezone,
      value: formatTimestampInTimezone(date, deviceTimezone),
      icon: Laptop,
    },
    {
      label: timezoneLabel,
      timezone,
      value: formatTimestampInTimezone(date, timezone),
      icon: House,
    },
    {
      label: "UTC",
      timezone: "UTC",
      value: formatTimestampInTimezone(date, "UTC"),
      icon: Globe,
    },
    {
      label: "UNIX",
      timezone: "UTC",
      value: String(Math.floor(date.getTime() / 1000)),
      icon: Terminal,
    },
  ];

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        if (controlledOpen === undefined) setInternalOpen(nextOpen);
      }}
    >
      <PopoverTrigger
        render={
          <button
            type="button"
            className="inline-flex appearance-none border-0 bg-transparent p-0 text-inherit"
            onMouseEnter={keepOpen}
            onMouseLeave={scheduleClose}
          >
            {children}
          </button>
        }
      />
      <PopoverContent
        side="top"
        align="start"
        className="w-[380px] max-w-[calc(100vw-2rem)] p-0"
        container={portalContainer}
        initialFocus={false}
        onMouseEnter={keepOpen}
        onMouseLeave={scheduleClose}
        onFocusCapture={keepOpen}
        onBlurCapture={scheduleClose}
      >
        <div className="grid grid-cols-[16px_max-content_minmax(0,1fr)_24px] items-center gap-x-1 gap-y-3 py-3 pr-1 pl-3">
          {rows.map((row) => {
            const abbreviation =
              row.label === "UNIX"
                ? ""
                : formatTimezoneAbbreviation(row.timezone, date);
            return (
              <ConversionRow
                key={row.label}
                abbreviation={abbreviation}
                icon={row.icon}
                label={row.label}
                value={row.value}
              />
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

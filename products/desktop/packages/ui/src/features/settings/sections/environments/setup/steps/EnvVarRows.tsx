import { Plus, X } from "@phosphor-icons/react";
import {
  type EnvVarRow,
  envVarError,
  splitPastedEnvVars,
} from "@posthog/core/settings/environmentSetup";
import { Button, Input, Text } from "@posthog/quill";
import { type ClipboardEvent, type ReactNode, useState } from "react";

interface EnvVarRowsProps {
  rows: readonly EnvVarRow[];
  /**
   * Names already saved on the environment. Values are never returned, so these
   * are listed rather than edited, and entering a row replaces all of them.
   */
  savedKeys?: readonly string[];
  onChange: (rows: EnvVarRow[]) => void;
}

/**
 * Environment variables as name and value pairs. Pasting a .env file fills the
 * rows out, since that is how people carry these between machines, and the
 * value column masks what it holds because most of them are secrets.
 */
export function EnvVarRows({
  rows,
  savedKeys = [],
  onChange,
}: EnvVarRowsProps) {
  const [skippedOnPaste, setSkippedOnPaste] = useState<string[]>([]);
  // Random ids, not row-count ones: a count repeats after delete-then-add,
  // and a repeated id makes patch() edit two rows at once.
  const nextId = () => crypto.randomUUID();

  const addRow = () =>
    onChange([...rows, { id: nextId(), key: "", value: "" }]);

  const patch = (id: string, part: Partial<EnvVarRow>) =>
    onChange(rows.map((row) => (row.id === id ? { ...row, ...part } : row)));

  /**
   * A paste that carries variables replaces the row it landed in, so pasting
   * into the first empty row does not leave a blank one behind. Keys the
   * sandbox manages are reported rather than added, because a row holding one
   * blocks the save and the sandbox drops it from the set anyway.
   */
  const handlePaste = (event: ClipboardEvent, row: EnvVarRow) => {
    const text = event.clipboardData.getData("text");
    const { entries, skipped } = splitPastedEnvVars(text);
    if (entries.length === 0 && skipped.length === 0) return;
    if (
      entries.length === 1 &&
      skipped.length === 0 &&
      !text.includes("\n") &&
      row.key.trim() !== ""
    ) {
      return;
    }
    event.preventDefault();
    setSkippedOnPaste(skipped);
    const added = entries.map((entry) => ({
      id: nextId(),
      ...entry,
    }));
    const isBlank = row.key.trim() === "" && row.value.trim() === "";
    onChange([
      ...rows.filter((current) => current.id !== row.id || !isBlank),
      ...added,
    ]);
  };

  const skippedNotice = skippedOnPaste.length > 0 && (
    <Text className="max-w-[64ch] text-(--gray-11) text-[11.5px] leading-snug">
      Left out {skippedOnPaste.length}{" "}
      {skippedOnPaste.length === 1 ? "variable" : "variables"} the sandbox
      manages: {skippedOnPaste.join(", ")}. Everything else was added.
    </Text>
  );

  /** Every branch ends with the paste notice, which outlives the rows it changed. */
  const wrap = (body: ReactNode) => (
    <div className="flex flex-col gap-2">
      {body}
      {skippedNotice}
    </div>
  );

  // Saved names with no rows entered yet is the resting state of an environment
  // that has variables. Listing them is the only way to tell it apart from one
  // that has none, since the values never come back from the API.
  if (rows.length === 0 && savedKeys.length > 0) {
    return wrap(
      <div
        className="flex flex-col gap-2"
        data-attr="environment-setup-saved-variables"
      >
        <ColumnHeadings />
        {savedKeys.map((key) => (
          <div key={key} className="flex max-w-[640px] items-center gap-2">
            <Text className="flex-1 font-mono text-(--gray-12) text-[12px]">
              {key}
            </Text>
            <Text className="flex-1 font-mono text-(--gray-10) text-[12px]">
              ••••••••
            </Text>
            <span className="w-7 shrink-0" />
          </div>
        ))}
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            data-attr="environment-setup-add-variable"
            onClick={addRow}
          >
            <Plus size={12} />
            Add a variable
          </Button>
          <Text className="text-(--gray-10) text-[11.5px]">
            Adding one replaces every variable listed here, so re-enter the ones
            you want to keep.
          </Text>
        </div>
      </div>,
    );
  }

  if (rows.length === 0) {
    return wrap(
      <div className="flex flex-col items-start gap-2 rounded-(--radius-3) border border-border border-dashed px-3 py-3">
        <Text className="text-(--gray-11) text-[11.5px]">
          None yet. Add them one at a time, or paste a .env file into the first
          row.
        </Text>
        <Button
          variant="outline"
          size="sm"
          data-attr="environment-setup-add-variable"
          onClick={addRow}
        >
          <Plus size={12} />
          Add a variable
        </Button>
      </div>,
    );
  }

  return wrap(
    <div className="flex flex-col gap-2">
      <ColumnHeadings />
      {rows.map((row, index) => {
        const error = envVarError(row, rows);
        return (
          <div key={row.id} className="flex flex-col gap-1">
            <div className="flex max-w-[640px] items-center gap-2">
              <Input
                className="h-7 flex-1 font-mono text-[12px]"
                value={row.key}
                placeholder="OPENAI_API_KEY"
                aria-label={`Variable ${index + 1} name`}
                data-attr={`environment-setup-variable-key-${index}`}
                onChange={(event) => patch(row.id, { key: event.target.value })}
                onPaste={(event) => handlePaste(event, row)}
              />
              <Input
                type="password"
                className="h-7 flex-1 font-mono text-[12px]"
                value={row.value}
                placeholder="sk-…"
                aria-label={`Variable ${index + 1} value`}
                data-attr={`environment-setup-variable-value-${index}`}
                onChange={(event) =>
                  patch(row.id, { value: event.target.value })
                }
                onPaste={(event) => handlePaste(event, row)}
              />
              <Button
                variant="link-muted"
                size="sm"
                className="w-7 shrink-0"
                aria-label={`Remove variable ${index + 1}`}
                onClick={() =>
                  onChange(rows.filter((current) => current.id !== row.id))
                }
              >
                <X size={12} />
              </Button>
            </div>
            {error && (
              <Text className="text-(--amber-11) text-[11.5px]">{error}</Text>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          data-attr="environment-setup-add-variable"
          onClick={addRow}
        >
          <Plus size={12} />
          Add a variable
        </Button>
        <Text className="text-(--gray-10) text-[11.5px]">
          Pasting a .env file fills out the rows.
        </Text>
      </div>
      {savedKeys.length > 0 && (
        <Text className="max-w-[64ch] text-(--amber-11) text-[11.5px] leading-snug">
          Saving these replaces the variables already on this environment:{" "}
          {savedKeys.join(", ")}. Remove every row to keep them instead.
        </Text>
      )}
    </div>,
  );
}

/** The name and value columns, above both the saved list and the editable rows. */
function ColumnHeadings() {
  return (
    <div className="flex max-w-[640px] items-center gap-2">
      <Text className="flex-1 text-(--gray-10) text-[11px]">Name</Text>
      <Text className="flex-1 text-(--gray-10) text-[11px]">Value</Text>
      <span className="w-7 shrink-0" />
    </div>
  );
}

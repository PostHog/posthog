// Shared select-style trigger for the onboarding folder picker and combobox fields.
// Apply directly to a DOM <button> or a forwardRef component that spreads props,
// not to a function-component wrapper (Base UI's render prop clones the element).
export const FIELD_TRIGGER_CLASS =
  "box-border flex w-full cursor-pointer appearance-none items-center justify-between gap-3 rounded-[10px] border border-(--gray-a3) bg-(--color-panel-solid) px-[14px] py-[10px] font-[inherit] text-sm shadow-[0_1px_3px_rgba(0,0,0,0.04),0_1px_2px_rgba(0,0,0,0.02)]";

export const FIELD_CONTENT_CLASS =
  "w-(--anchor-width) max-w-(--anchor-width) min-w-(--anchor-width) p-0";

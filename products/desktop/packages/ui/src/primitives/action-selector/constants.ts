export const OTHER_OPTION_ID = "_other";
export const OTHER_OPTION_ID_ALT = "other";
export const SUBMIT_OPTION_ID = "_submit";
export const CANCEL_OPTION_ID = "cancel";
export const OPTION_ID_PREFIX = "option_";

export function isOtherOption(optionId: string): boolean {
  return optionId === OTHER_OPTION_ID || optionId === OTHER_OPTION_ID_ALT;
}

export function isSubmitOption(optionId: string): boolean {
  return optionId === SUBMIT_OPTION_ID;
}

export function isCancelOption(optionId: string): boolean {
  return optionId === CANCEL_OPTION_ID;
}

export function filterOtherOptions(ids: string[]): string[] {
  return ids.filter((id) => !isOtherOption(id));
}

export function parseOptionIndex(optionId: string): number {
  return Number.parseInt(optionId.replace(OPTION_ID_PREFIX, ""), 10);
}

export function makeOptionId(index: number): string {
  return `${OPTION_ID_PREFIX}${index}`;
}

export function shouldShowChannelContextChip(
  includeChannelContext: boolean,
  channelContextPath?: string,
): boolean {
  return includeChannelContext && !channelContextPath;
}

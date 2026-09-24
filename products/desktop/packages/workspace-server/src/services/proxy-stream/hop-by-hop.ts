const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-connection",
  "te",
  "trailer",
  "upgrade",
  "transfer-encoding",
];

/** Hop-by-hop names plus any header the Connection value lists. */
export function hopByHop(
  connection: string | string[] | null | undefined,
): Set<string> {
  const listed = [connection ?? []]
    .flat()
    .flatMap((value) => value.split(","))
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...HOP_BY_HOP_HEADERS, ...listed]);
}

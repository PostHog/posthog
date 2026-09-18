import { useEffect, useState } from "react";

const MINUTE_MS = 60_000;

/**
 * The current time, changing once a minute. Lists that show "next run in 3m"
 * need a `now`, and `new Date()` in the render body gives every scroll frame a
 * new one, which re-does the work of every visible row.
 */
export function useMinuteNow(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), MINUTE_MS);
    return () => clearInterval(timer);
  }, []);

  return now;
}

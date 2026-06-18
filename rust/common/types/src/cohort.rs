use std::collections::HashSet;
use std::str::FromStr;

/// Which teams the realtime-cohort shadow pipeline is scoped to, parsed from
/// `REALTIME_COHORT_TEAM_ALLOWLIST`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TeamAllowlist {
    All,
    Only(HashSet<i32>),
}

impl TeamAllowlist {
    /// Whether `team_id` is in scope.
    pub fn includes(&self, team_id: i32) -> bool {
        match self {
            TeamAllowlist::All => true,
            TeamAllowlist::Only(ids) => ids.contains(&team_id),
        }
    }
}

impl FromStr for TeamAllowlist {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        // envconfig's `default` only covers an *unset* var; a set-but-empty value must still mean
        // "no gate", never "gate everything".
        if s.is_empty() || s.eq_ignore_ascii_case("all") || s == "*" {
            return Ok(TeamAllowlist::All);
        }
        if s.eq_ignore_ascii_case("none") {
            return Ok(TeamAllowlist::Only(HashSet::new()));
        }

        let mut ids = HashSet::new();
        for part in s.split(',').map(str::trim).filter(|p| !p.is_empty()) {
            match part.split_once(':') {
                Some((start, end)) => {
                    let start: i32 = start
                        .trim()
                        .parse()
                        .map_err(|e| format!("invalid range start in '{part}': {e}"))?;
                    let end: i32 = end
                        .trim()
                        .parse()
                        .map_err(|e| format!("invalid range end in '{part}': {e}"))?;
                    if end < start {
                        return Err(format!("invalid range '{part}': end < start"));
                    }
                    // Guard against an unbounded span materializing billions of ids (OOM at
                    // startup). Compute in i64 so a negative start vs i32::MAX end can't overflow.
                    const MAX_RANGE_SPAN: i64 = 100_000;
                    let span = i64::from(end) - i64::from(start) + 1;
                    if span > MAX_RANGE_SPAN {
                        return Err(format!(
                            "range '{part}' spans {span} teams (max {MAX_RANGE_SPAN}); use 'all' or '*' to allow every team"
                        ));
                    }
                    ids.extend(start..=end);
                }
                None => {
                    let id: i32 = part
                        .parse()
                        .map_err(|e| format!("invalid team id '{part}': {e}"))?;
                    ids.insert(id);
                }
            }
        }
        Ok(TeamAllowlist::Only(ids))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_allowlist_blank_and_keywords_disable_or_clear_the_gate() {
        assert_eq!("".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("  ".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("all".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("ALL".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("*".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!(
            "none".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::new()),
        );
    }

    #[test]
    fn team_allowlist_parses_lists_and_ranges() {
        assert_eq!(
            "2".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([2])),
        );
        assert_eq!(
            "2, 42 ,7".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([2, 42, 7])),
        );
        assert_eq!(
            "1:3".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([1, 2, 3])),
        );
        assert_eq!(
            "1:2,5".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([1, 2, 5])),
        );
    }

    #[test]
    fn team_allowlist_rejects_garbage_and_inverted_ranges() {
        assert!("nope".parse::<TeamAllowlist>().is_err());
        assert!("3:1".parse::<TeamAllowlist>().is_err());
        assert!("2,x".parse::<TeamAllowlist>().is_err());
        // Oversized spans would materialize billions of ids and OOM at startup.
        assert!("1:2000000000".parse::<TeamAllowlist>().is_err());
        assert!("1:100002".parse::<TeamAllowlist>().is_err());
        // A span at exactly the cap (100_000 teams) is still allowed.
        assert!("1:100000".parse::<TeamAllowlist>().is_ok());
    }

    #[test]
    fn team_allowlist_includes_honours_scope() {
        assert!(TeamAllowlist::All.includes(999));
        let only = TeamAllowlist::Only(HashSet::from([2]));
        assert!(only.includes(2));
        assert!(!only.includes(3));
        assert!(!TeamAllowlist::Only(HashSet::new()).includes(2));
    }

    #[test]
    fn team_allowlist_default_is_team_two() {
        // envconfig default is "2"; a set-but-empty var falls through to `All` (see `FromStr`).
        assert_eq!(
            "2".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([2])),
        );
    }
}

//! Per-team gate parsed from an environment variable.

use std::collections::HashSet;
use std::str::FromStr;

/// Which teams a gated behavior applies to.
///
/// An unset or empty value gates nothing. That is deliberately the opposite
/// of the realtime-cohort allowlist in `common-types`, where empty means
/// every team: a gate on person deletes must fail closed.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub enum TeamAllowlist {
    #[default]
    None,
    All,
    Only(HashSet<i64>),
}

impl TeamAllowlist {
    pub fn includes(&self, team_id: i64) -> bool {
        match self {
            TeamAllowlist::None => false,
            TeamAllowlist::All => true,
            TeamAllowlist::Only(ids) => ids.contains(&team_id),
        }
    }
}

impl FromStr for TeamAllowlist {
    type Err = String;

    /// Accepts `*` for every team or a comma-separated list of team ids.
    /// A malformed id is an error rather than a silently dropped entry, so
    /// a typo in a deploy fails startup instead of leaving one team on the
    /// wrong path.
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        if s.is_empty() {
            return Ok(TeamAllowlist::None);
        }
        if s == "*" {
            return Ok(TeamAllowlist::All);
        }
        let mut ids = HashSet::new();
        for part in s.split(',').map(str::trim).filter(|p| !p.is_empty()) {
            let id: i64 = part
                .parse()
                .map_err(|e| format!("invalid team id '{part}': {e}"))?;
            ids.insert(id);
        }
        Ok(TeamAllowlist::Only(ids))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_gates_nothing() {
        let allowlist: TeamAllowlist = "".parse().unwrap();
        assert_eq!(allowlist, TeamAllowlist::None);
        assert!(!allowlist.includes(1));
        assert_eq!("  ".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::None);
    }

    #[test]
    fn star_matches_every_team() {
        let allowlist: TeamAllowlist = "*".parse().unwrap();
        assert!(allowlist.includes(1));
        assert!(allowlist.includes(i64::MAX));
    }

    #[test]
    fn list_matches_only_listed_teams() {
        let allowlist: TeamAllowlist = " 2, 15 ,,300".parse().unwrap();
        assert!(allowlist.includes(2));
        assert!(allowlist.includes(15));
        assert!(allowlist.includes(300));
        assert!(!allowlist.includes(3));
    }

    #[test]
    fn malformed_id_is_an_error() {
        assert!("2,abc".parse::<TeamAllowlist>().is_err());
        assert!("all".parse::<TeamAllowlist>().is_err());
    }
}

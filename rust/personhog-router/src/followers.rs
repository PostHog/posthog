//! The router's side of the follower instances: one routing table per instance, and
//! nothing held during a follower handoff.

use async_trait::async_trait;
use personhog_coordination::error::Result;
use personhog_coordination::routing_table::StashHandler;
use tokio_util::sync::CancellationToken;

/// One follower coordination instance, such as the followers of one zone.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FollowerInstanceSpec {
    pub name: String,
    pub etcd_prefix: String,
}

/// Parse `name=prefix,name=prefix`, putting the instance named `preferred` first so the
/// router reads from its own zone before any other.
pub fn parse_instances(
    raw: &str,
    preferred: &str,
) -> std::result::Result<Vec<FollowerInstanceSpec>, String> {
    let mut instances = Vec::new();
    for entry in raw
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
    {
        let (name, prefix) = entry
            .split_once('=')
            .filter(|(name, prefix)| !name.is_empty() && !prefix.is_empty())
            .ok_or_else(|| format!("follower instance `{entry}` is not `name=etcd-prefix`"))?;
        instances.push(FollowerInstanceSpec {
            name: name.to_string(),
            etcd_prefix: prefix.to_string(),
        });
    }
    instances.sort_by_key(|instance| instance.name != preferred);
    Ok(instances)
}

/// A follower handoff holds no requests: reads need no exclusivity, so they stay on the
/// old owner until the routing table flips to the new one at `Complete`.
pub struct NoHold;

#[async_trait]
impl StashHandler for NoHold {
    async fn begin_stash(&self, _partition: u32, _new_owner: &str) -> Result<()> {
        Ok(())
    }

    async fn drain_stash(
        &self,
        _partition: u32,
        _target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        Ok(())
    }

    fn stash_pending(&self, _partition: u32) -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(instances: &[FollowerInstanceSpec]) -> Vec<&str> {
        instances
            .iter()
            .map(|instance| instance.name.as_str())
            .collect()
    }

    #[test]
    fn the_preferred_instance_comes_first_and_the_rest_keep_their_order() {
        let raw = "use1a=/followers-a/, use1b=/followers-b/,use1c=/followers-c/";

        let instances = parse_instances(raw, "use1b").expect("parsed");

        assert_eq!(names(&instances), ["use1b", "use1a", "use1c"]);
        assert_eq!(instances[0].etcd_prefix, "/followers-b/");
        assert_eq!(
            names(&parse_instances(raw, "").expect("parsed")),
            ["use1a", "use1b", "use1c"]
        );
    }

    #[test]
    fn an_entry_without_a_name_or_a_prefix_is_refused() {
        for raw in ["use1a", "=/followers-a/", "use1a="] {
            assert!(parse_instances(raw, "").is_err(), "{raw}");
        }
        assert_eq!(parse_instances("", ""), Ok(Vec::new()));
    }
}

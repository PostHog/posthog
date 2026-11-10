use std::collections::HashMap;

use common_redis::{CustomRedisError, ScriptRunner};
use sha2::{Digest, Sha256};
use uuid::Uuid;

pub const DAY_SECONDS: i64 = 86_400;
pub const SHORT_WINDOW_SECONDS: i64 = 600;
pub const HISTORY_DAYS: usize = 14;

const DAYS_TTL_SECONDS: i64 = (HISTORY_DAYS as i64 + 2) * DAY_SECONDS;
const SHORT_TTL_SECONDS: i64 = SHORT_WINDOW_SECONDS + 60;
// A late pod can still write to a day after it ends, so the client counts outlive the day.
const CLIENT_DAY_GRACE_SECONDS: i64 = 3_600;

// KEYS[1] is the team's daily totals. Each client group then owns two keys:
// its issue's client counts for the day, and for the short window.
// ARGV[8..] holds one (client, count) pair per client group, in key order.
const RECORD_LUA: &str = r#"
local day = tonumber(ARGV[1])
local history = tonumber(ARGV[2])
local total = tonumber(ARGV[3])
local days_ttl = tonumber(ARGV[4])
local client_day_ttl = tonumber(ARGV[5])
local short_ttl = tonumber(ARGV[6])
local client_cap = tonumber(ARGV[7])

local function count_client(key, client, n, ttl)
  local before = redis.call('hget', key, client)
  if before then
    redis.call('hincrby', key, client, n)
    return tonumber(before)
  end
  local clients = redis.call('hlen', key)
  if clients >= client_cap then return -1 end
  redis.call('hset', key, client, n)
  if clients == 0 then redis.call('expire', key, ttl) end
  return 0
end

local today = 'n' .. day
local new_day = redis.call('hexists', KEYS[1], today) == 0
redis.call('hincrby', KEYS[1], today, total)
if new_day then
  for _, field in ipairs(redis.call('hkeys', KEYS[1])) do
    local field_day = tonumber(string.sub(field, 2))
    if field_day and field_day < day - history then
      redis.call('hdel', KEYS[1], field)
    end
  end
  redis.call('expire', KEYS[1], days_ttl)
end

local out = {}
for offset = 0, history do
  local counts = redis.call('hmget', KEYS[1], 'n' .. (day - offset), 'x' .. (day - offset))
  out[#out + 1] = tonumber(counts[1]) or 0
  out[#out + 1] = tonumber(counts[2]) or 0
end
for group = 0, (#ARGV - 7) / 2 - 1 do
  local client = ARGV[8 + 2 * group]
  local n = tonumber(ARGV[9 + 2 * group])
  out[#out + 1] = count_client(KEYS[2 + 2 * group], client, n, client_day_ttl)
  out[#out + 1] = count_client(KEYS[3 + 2 * group], client, n, short_ttl)
end
return out
"#;

const RECORD_REMOVED_LUA: &str = r#"
return { redis.call('hincrby', KEYS[1], ARGV[1], tonumber(ARGV[2])) }
"#;

/// The events of one batch that one client sent for one issue.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientGroup {
    pub issue_id: Uuid,
    pub client: String,
    pub events: u32,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DayCount {
    pub events: u64,
    /// Events that the per-issue rules would have removed before the project cap.
    pub removed: u64,
}

impl DayCount {
    pub fn kept(&self) -> u64 {
        self.events.saturating_sub(self.removed)
    }
}

/// A client's counts for one issue before the current batch. `None` means the
/// issue already tracks the maximum number of clients and this client is not one of them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClientCount {
    pub day: Option<u64>,
    pub short_window: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TeamSnapshot {
    /// Today, including the current batch.
    pub today: DayCount,
    /// The previous `HISTORY_DAYS` days, most recent first.
    pub history: Vec<DayCount>,
    /// One entry per input client group, in input order.
    pub clients: Vec<ClientCount>,
}

#[derive(Debug, Clone, Copy)]
pub struct Ledger {
    pub client_cap: u32,
}

impl Ledger {
    /// Count one team's batch and return the counts the rules decide from.
    /// `total` includes events without a client, which no group carries.
    pub async fn record(
        &self,
        redis: &dyn ScriptRunner,
        team_id: i32,
        now: i64,
        total: u32,
        groups: &[ClientGroup],
    ) -> Result<TeamSnapshot, CustomRedisError> {
        let day = now.div_euclid(DAY_SECONDS);
        let short_window = now.div_euclid(SHORT_WINDOW_SECONDS);
        let client_day_ttl = (day + 1) * DAY_SECONDS - now + CLIENT_DAY_GRACE_SECONDS;

        let mut keys = vec![days_key(team_id)];
        let mut args = vec![
            day.to_string(),
            HISTORY_DAYS.to_string(),
            total.to_string(),
            DAYS_TTL_SECONDS.to_string(),
            client_day_ttl.to_string(),
            SHORT_TTL_SECONDS.to_string(),
            self.client_cap.to_string(),
        ];
        for group in groups {
            keys.push(format!("et:c1:{{{team_id}}}:l:{day}:{}", group.issue_id));
            keys.push(format!(
                "et:c1:{{{team_id}}}:s:{short_window}:{}",
                group.issue_id
            ));
            args.push(client_field(&group.client));
            args.push(group.events.to_string());
        }

        let reply = redis.eval_int_vec(RECORD_LUA, keys, args).await?;
        decode(&reply, total, groups.len())
            .ok_or_else(|| CustomRedisError::ParseError("invalid adaptive ledger reply".into()))
    }

    /// Add to today's count of events that the per-issue rules would have removed.
    pub async fn record_removed(
        &self,
        redis: &dyn ScriptRunner,
        team_id: i32,
        now: i64,
        removed: u32,
    ) -> Result<(), CustomRedisError> {
        let day = now.div_euclid(DAY_SECONDS);
        redis
            .eval_int_vec(
                RECORD_REMOVED_LUA,
                vec![days_key(team_id)],
                vec![format!("x{day}"), removed.to_string()],
            )
            .await
            .map(|_| ())
    }
}

fn days_key(team_id: i32) -> String {
    format!("et:c1:{{{team_id}}}:days")
}

// A distinct id can be 200 characters long. A fixed-size hash bounds the memory of each entry.
fn client_field(client: &str) -> String {
    let hash = Sha256::digest(client.as_bytes());
    format!(
        "{:016x}",
        u64::from_be_bytes(hash[0..8].try_into().expect("sha256 has 32 bytes"))
    )
}

fn decode(reply: &[i64], total: u32, groups: usize) -> Option<TeamSnapshot> {
    let day_values = 2 * (HISTORY_DAYS + 1);
    if reply.len() != day_values + 2 * groups {
        return None;
    }
    let (days, clients) = reply.split_at(day_values);
    let days = days
        .chunks_exact(2)
        .map(|pair| {
            Some(DayCount {
                events: u64::try_from(pair[0]).ok()?,
                removed: u64::try_from(pair[1]).ok()?,
            })
        })
        .collect::<Option<Vec<_>>>()?;
    if days[0].events < u64::from(total) {
        return None;
    }
    let clients = clients
        .chunks_exact(2)
        .map(|pair| ClientCount {
            day: u64::try_from(pair[0]).ok(),
            short_window: u64::try_from(pair[1]).ok(),
        })
        .collect();
    Some(TeamSnapshot {
        today: days[0],
        history: days[1..].to_vec(),
        clients,
    })
}

/// Group a team's events by (issue, client), in order of first appearance.
/// Returns the groups and, for each input event, the index of its group.
pub fn group_clients(events: &[(Uuid, Option<&str>)]) -> (Vec<ClientGroup>, Vec<Option<usize>>) {
    let mut index: HashMap<(Uuid, &str), usize> = HashMap::new();
    let mut groups: Vec<ClientGroup> = Vec::new();
    let membership = events
        .iter()
        .map(|(issue_id, client)| {
            let client = (*client)?;
            let group = *index.entry((*issue_id, client)).or_insert_with(|| {
                groups.push(ClientGroup {
                    issue_id: *issue_id,
                    client: client.to_owned(),
                    events: 0,
                });
                groups.len() - 1
            });
            groups[group].events += 1;
            Some(group)
        })
        .collect();
    (groups, membership)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{start_redis, FakeRunner};

    const LEDGER: Ledger = Ledger { client_cap: 2 };

    fn group(issue_id: Uuid, client: &str, events: u32) -> ClientGroup {
        ClientGroup {
            issue_id,
            client: client.into(),
            events,
        }
    }

    #[tokio::test]
    async fn rejects_a_reply_that_does_not_match_the_batch() {
        let issue = Uuid::now_v7();
        let groups = [group(issue, "a", 1)];
        for reply in [
            vec![0; 30],
            std::iter::once(-1).chain(vec![0; 31]).collect(),
            vec![0; 32],
        ] {
            let result = LEDGER
                .record(&*FakeRunner::returning(reply), 7, 0, 1, &groups)
                .await;
            assert!(result.is_err());
        }
    }

    #[test]
    fn groups_events_by_issue_and_client_in_first_seen_order() {
        let (first, second) = (Uuid::now_v7(), Uuid::now_v7());
        let (groups, membership) = group_clients(&[
            (first, Some("a")),
            (first, None),
            (second, Some("a")),
            (first, Some("a")),
        ]);
        assert_eq!(groups, [group(first, "a", 2), group(second, "a", 1)]);
        assert_eq!(membership, [Some(0), None, Some(1), Some(0)]);
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn counts_days_and_clients_across_window_boundaries() {
        let (redis, _container) = start_redis().await;
        let issue = Uuid::now_v7();
        let looping = [group(issue, "looping", 3)];

        let first = LEDGER.record(&*redis, 7, 0, 4, &looping).await.unwrap();
        assert_eq!(first.today.events, 4);
        assert_eq!(
            first.clients,
            [ClientCount {
                day: Some(0),
                short_window: Some(0)
            }]
        );

        LEDGER.record_removed(&*redis, 7, 0, 1).await.unwrap();
        let next_window = LEDGER
            .record(&*redis, 7, SHORT_WINDOW_SECONDS, 3, &looping)
            .await
            .unwrap();
        assert_eq!(
            next_window.today,
            DayCount {
                events: 7,
                removed: 1
            }
        );
        assert_eq!(
            next_window.clients,
            [ClientCount {
                day: Some(3),
                short_window: Some(0)
            }]
        );

        let other_team = LEDGER.record(&*redis, 8, 0, 3, &looping).await.unwrap();
        assert_eq!(other_team.today.events, 3);
        assert_eq!(other_team.clients[0].day, Some(0));

        let next_day = LEDGER
            .record(&*redis, 7, DAY_SECONDS, 3, &looping)
            .await
            .unwrap();
        assert_eq!(next_day.today.events, 3);
        assert_eq!(next_day.history[0].kept(), 6);
        assert_eq!(next_day.clients[0].day, Some(0));

        let after_history = LEDGER
            .record(&*redis, 7, (HISTORY_DAYS as i64 + 1) * DAY_SECONDS, 1, &[])
            .await
            .unwrap();
        assert_eq!(after_history.history[HISTORY_DAYS - 1].events, 3);
        assert!(after_history.history[..HISTORY_DAYS - 1]
            .iter()
            .all(|day| day.events == 0));
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn stops_adding_clients_at_the_cap_but_keeps_counting_known_ones() {
        let (redis, _container) = start_redis().await;
        let issue = Uuid::now_v7();
        let groups = [
            group(issue, "a", 1),
            group(issue, "b", 1),
            group(issue, "c", 1),
        ];
        LEDGER.record(&*redis, 7, 0, 3, &groups).await.unwrap();
        let second = LEDGER.record(&*redis, 7, 0, 3, &groups).await.unwrap();
        let days: Vec<_> = second.clients.iter().map(|client| client.day).collect();
        assert_eq!(days, [Some(1), Some(1), None]);
    }
}

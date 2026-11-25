#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

use chrono::{DateTime, TimeDelta, Utc};
use meep_topic::{Matcher, Message, Rule, RuleEffect, Source};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

pub use meep_topic::{Verdict, decide};

/// Eligible natural-language skip rules, newest first. The model judges applicability.
pub fn skip_candidates<'a>(
    rules: &'a [Rule],
    message: &'a Message,
) -> impl Iterator<Item = &'a Rule> {
    rules.iter().rev().filter(
        move |rule| matches!(&rule.effect, RuleEffect::Skip(m) if matches_message(m,message)),
    )
}

fn matches_message(matcher: &Matcher, message: &Message) -> bool {
    let target = message.reply_target();
    let (connection, channel) = match &target {
        Some(Source::Connection {
            connection,
            channel,
        }) => (Some(connection.as_str()), Some(channel.as_str())),
        _ => (None, None),
    };
    matcher
        .connection
        .as_deref()
        .is_none_or(|c| Some(c) == connection)
        && matcher
            .channel
            .as_deref()
            .is_none_or(|c| Some(c) == channel)
}

pub use meep_topic::rule_from_approval;

/// Delivery and agent-run budgets configured by the host.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Limits {
    /// Largest hop count that may be delivered.
    pub max_hops: u32,
    /// Number of starts allowed in a rolling hour.
    pub max_runs_per_hour: usize,
}

impl Limits {
    /// Allows delivery through the configured hop count, inclusive.
    pub fn hop_ok(&self, hops: u32) -> bool {
        hops <= self.max_hops
    }
}

/// Persisted start times for one topic's rolling one-hour run budget.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RunWindow(VecDeque<DateTime<Utc>>);

impl RunWindow {
    /// Whether another run could start at `now` under the current host limits.
    pub fn has_capacity(&self, now: DateTime<Utc>, limits: Limits) -> bool {
        self.0.back().is_none_or(|&last| last <= now)
            && self
                .0
                .iter()
                .rev()
                .take_while(|&&at| now - at < TimeDelta::hours(1))
                .count()
                < limits.max_runs_per_hour
    }

    /// Earliest UTC instant another run can start, or none when starts are disabled.
    pub fn next_start(&self, now: DateTime<Utc>, limits: Limits) -> Option<DateTime<Utc>> {
        let index = limits.max_runs_per_hour.checked_sub(1)?;
        let earliest = self.0.back().copied().unwrap_or(now).max(now);
        match self.0.iter().rev().nth(index) {
            Some(at) => at
                .checked_add_signed(TimeDelta::hours(1))
                .map(|end| end.max(earliest)),
            None => Some(earliest),
        }
    }

    /// Reserve a start if capacity remains. A start expires at exactly one hour.
    pub fn try_start(&mut self, now: DateTime<Utc>, limits: Limits) -> bool {
        if !self.has_capacity(now, limits) {
            return false;
        }
        self.0.retain(|&at| now - at < TimeDelta::hours(1));
        self.0.push_back(now);
        true
    }
}

#[cfg(test)]
mod tests;

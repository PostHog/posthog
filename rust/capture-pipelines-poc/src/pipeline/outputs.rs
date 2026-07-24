//! The analytics pipeline's redirect targets and topic map.

use crate::framework::chain::IntoOutputs;
use crate::framework::result::Outputs;

/// The demo analytics pipeline's redirect targets.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AnalyticsOutputs {
    /// Hot-key overflow lane.
    Overflow,
    /// Dead-letter topic.
    Dlq,
}

impl Outputs for AnalyticsOutputs {
    const ALL: &'static [Self] = &[AnalyticsOutputs::Overflow, AnalyticsOutputs::Dlq];

    fn name(&self) -> &'static str {
        match self {
            AnalyticsOutputs::Overflow => "overflow",
            AnalyticsOutputs::Dlq => "dlq",
        }
    }
}

// Identity lift, so a chain ending in `AnalyticsOutputs` unifies with itself. (The
// `NoOutputs → O` lift is provided blanket-style in `framework::chain`.)
impl IntoOutputs<AnalyticsOutputs> for AnalyticsOutputs {
    fn into_outputs(self) -> AnalyticsOutputs {
        self
    }
}

/// Topic resolver for the analytics outputs — every variant is configured, so
/// [`OutputRegistry::check`](crate::framework::outputs::OutputRegistry::check) passes.
pub fn analytics_topic_for(output: AnalyticsOutputs) -> Option<&'static str> {
    match output {
        AnalyticsOutputs::Overflow => Some("events_overflow"),
        AnalyticsOutputs::Dlq => Some("events_dlq"),
    }
}

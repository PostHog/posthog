use serde::{Deserialize, Serialize};
use std::{fmt, str::FromStr};
use uuid::Uuid;

macro_rules! id {
    ($name:ident, $doc:literal) => {
        #[doc = $doc]
        #[derive(
            Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize,
        )]
        #[serde(transparent)]
        pub struct $name(pub Uuid);

        impl From<Uuid> for $name {
            fn from(value: Uuid) -> Self {
                Self(value)
            }
        }
        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(f)
            }
        }
        impl FromStr for $name {
            type Err = uuid::Error;
            fn from_str(s: &str) -> Result<Self, Self::Err> {
                Ok(Self(s.parse()?))
            }
        }
    };
}

id!(TopicId, "Stable ID of a topic.");
id!(ThreadId, "Stable ID of an inbox thread.");
id!(MessageId, "Stable ID of an incoming message.");
id!(TaskId, "Stable ID of a task.");
id!(FactId, "Stable ID of a fact.");
id!(RuleId, "Stable ID of a policy rule.");
id!(GoalId, "Stable ID of a goal.");
id!(WatchId, "Stable ID of a watch.");

id!(
    CommandId,
    "Identity retained across retries of a person’s command."
);

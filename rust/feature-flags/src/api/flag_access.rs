//! Port of the checks that Django's `AccessControlPermission` runs on the `remote_config` action
//! for a personal-API-key user. The rules live in
//! `products/access_control/backend/facade/user_access_control.py`. Both resolution orders are
//! ported: `uses_most_specific_access_resolution` lets the most specific subject decide, and the
//! legacy order lets member and role rules compete on level.

use crate::{api::errors::FlagError, database::get_connection_with_metrics, router::State};
use sqlx::FromRow;
use tracing::warn;
use uuid::Uuid;

const ORGANIZATION_ADMIN_LEVEL: i16 = 8;

trait Level: Copy + Ord {
    const NONE: Self;
    /// The level when no rule applies (`default_access_level` in Django).
    const DEFAULT: Self;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum ProjectLevel {
    None,
    Member,
    Admin,
}

impl Level for ProjectLevel {
    const NONE: Self = Self::None;
    const DEFAULT: Self = Self::Admin;
}

impl ProjectLevel {
    fn parse(value: &str) -> Self {
        match value {
            "member" => Self::Member,
            "admin" => Self::Admin,
            // Django fails the request on a level it does not know. Here the rule gives no access.
            _ => Self::None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum FlagLevel {
    None,
    Viewer,
    Editor,
    Manager,
}

impl Level for FlagLevel {
    const NONE: Self = Self::None;
    const DEFAULT: Self = Self::Editor;
}

impl FlagLevel {
    fn parse(value: &str) -> Self {
        match value {
            "viewer" => Self::Viewer,
            "editor" => Self::Editor,
            "manager" => Self::Manager,
            _ => Self::None,
        }
    }
}

/// Who a rule names, from the least to the most specific.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum Subject {
    Everyone,
    Role,
    Member,
}

#[derive(Clone, Copy, Debug)]
struct Rule<L> {
    subject: Subject,
    level: L,
}

fn highest<L: Level>(rules: &[Rule<L>]) -> Option<L> {
    rules.iter().map(|rule| rule.level).max()
}

fn most_specific<L: Level>(rules: &[Rule<L>]) -> Option<Rule<L>> {
    let subject = rules.iter().map(|rule| rule.subject).max()?;
    let level = rules
        .iter()
        .filter(|rule| rule.subject == subject)
        .map(|rule| rule.level)
        .max()?;
    Some(Rule { subject, level })
}

fn resource_level<L: Level>(rules: &[Rule<L>], most_specific_order: bool) -> Option<L> {
    if most_specific_order {
        most_specific(rules).map(|rule| rule.level)
    } else {
        highest(rules)
    }
}

fn object_level<L: Level>(object: &[Rule<L>], resource: Option<L>, most_specific_order: bool) -> L {
    if most_specific_order {
        let inherited = resource.unwrap_or(L::DEFAULT);
        return match most_specific(object) {
            // A rule for everyone on the object cannot open an object that the resource closes.
            // A rule for the member or one of their roles can.
            Some(rule)
                if rule.subject == Subject::Everyone
                    && rule.level != L::NONE
                    && inherited == L::NONE =>
            {
                L::NONE
            }
            Some(rule) => rule.level,
            None => inherited,
        };
    }

    let explicit: Vec<Rule<L>> = object
        .iter()
        .copied()
        .filter(|rule| rule.subject != Subject::Everyone)
        .collect();
    if let Some(level) = highest(&explicit) {
        return level;
    }
    // Only rules for everyone are left. A private object stays private even when the resource
    // gives more.
    let object_default = highest(object);
    if object_default == Some(L::NONE) {
        return L::NONE;
    }
    resource.or(object_default).unwrap_or(L::DEFAULT)
}

#[derive(Debug)]
pub enum FlagAccess {
    NoMembership,
    /// An organization admin, or an organization without the access control feature, where
    /// Django reads no rules.
    Unrestricted,
    Rules(AccessRules),
}

#[derive(Debug, Default)]
pub struct AccessRules {
    user_id: i32,
    most_specific_order: bool,
    project: Vec<Rule<ProjectLevel>>,
    flags: Vec<Rule<FlagLevel>>,
    flag_objects: Vec<(String, Rule<FlagLevel>)>,
}

impl FlagAccess {
    /// Django's `has_permission`: access to the project, and to feature flags in general.
    pub fn allows_flags(&self) -> bool {
        match self {
            Self::NoMembership => false,
            Self::Unrestricted => true,
            Self::Rules(rules) => rules.allows_project() && rules.allows_flag_resource(),
        }
    }

    /// Django's `has_object_permission` for one flag.
    pub fn allows_flag(&self, flag_id: i32, created_by_id: Option<i32>) -> bool {
        match self {
            Self::NoMembership => false,
            Self::Unrestricted => true,
            Self::Rules(rules) => rules.allows_flag(flag_id, created_by_id),
        }
    }

    pub async fn load(state: &State, team_id: i32, user_id: i32) -> Result<Self, FlagError> {
        let client: common_database::PostgresReader =
            state.database_pools.non_persons_reader.clone();
        let mut conn =
            get_connection_with_metrics(&client, "non_persons_reader", "remote_config_access")
                .await
                .map_err(|e| {
                    warn!("remote_config access: failed to get db connection: {e}");
                    FlagError::DatabaseUnavailable
                })?;

        let membership: Option<MembershipRow> = sqlx::query_as(
            r#"SELECT
                om.id AS membership_id,
                o.id AS organization_id,
                om.level::smallint AS level,
                EXISTS (
                    SELECT 1 FROM unnest(o.available_product_features) feature
                    WHERE feature->>'key' = 'access_control'
                ) AS access_control,
                EXISTS (
                    SELECT 1 FROM unnest(o.available_product_features) feature
                    WHERE feature->>'key' = 'role_based_access'
                ) AS role_based_access,
                COALESCE(o.uses_most_specific_access_resolution, false) AS most_specific_order
            FROM posthog_team t
            JOIN posthog_organization o ON o.id = t.organization_id
            JOIN posthog_organizationmembership om
                ON om.organization_id = o.id AND om.user_id = $2
            WHERE t.id = $1"#,
        )
        .bind(team_id)
        .bind(user_id)
        .fetch_optional(&mut *conn)
        .await
        .map_err(|e| {
            warn!("remote_config access: membership query failed: {e}");
            FlagError::DatabaseUnavailable
        })?;

        let Some(membership) = membership else {
            return Ok(Self::NoMembership);
        };
        if membership.level >= ORGANIZATION_ADMIN_LEVEL || !membership.access_control {
            return Ok(Self::Unrestricted);
        }

        // Django reads a rule only when it names everyone, the user's membership in this
        // organization, or a role the user holds in it. Roles count only with the role based
        // access feature, and a rule that names both a member and a role applies to nobody.
        let rows: Vec<RuleRow> = sqlx::query_as(
            r#"SELECT
                ac.resource,
                ac.resource_id,
                ac.access_level,
                ac.organization_member_id IS NOT NULL AS is_member,
                ac.role_id IS NOT NULL AS is_role
            FROM ee_accesscontrol ac
            WHERE ac.team_id = $1
              AND (
                  (ac.resource = 'project' AND ac.resource_id = $1::text)
                  OR ac.resource = 'feature_flag'
              )
              AND (
                  (ac.organization_member_id IS NULL AND ac.role_id IS NULL)
                  OR (ac.role_id IS NULL AND ac.organization_member_id = $2)
                  OR (
                      ac.organization_member_id IS NULL
                      AND $3
                      AND ac.role_id IN (
                          SELECT rm.role_id
                          FROM ee_rolemembership rm
                          JOIN ee_role r ON r.id = rm.role_id
                          LEFT JOIN posthog_organizationmembership rom
                              ON rom.id = rm.organization_member_id
                          WHERE rm.user_id = $4
                            AND r.organization_id = $5
                            AND (
                                rm.organization_member_id IS NULL
                                OR rom.organization_id = r.organization_id
                            )
                      )
                  )
              )"#,
        )
        .bind(team_id)
        .bind(membership.membership_id)
        .bind(membership.role_based_access)
        .bind(user_id)
        .bind(membership.organization_id)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| {
            warn!("remote_config access: rules query failed: {e}");
            FlagError::DatabaseUnavailable
        })?;

        let mut rules = AccessRules {
            user_id,
            most_specific_order: membership.most_specific_order,
            ..AccessRules::default()
        };
        for row in rows {
            let subject = if row.is_member {
                Subject::Member
            } else if row.is_role {
                Subject::Role
            } else {
                Subject::Everyone
            };
            match (row.resource.as_str(), row.resource_id) {
                ("project", _) => rules.project.push(Rule {
                    subject,
                    level: ProjectLevel::parse(&row.access_level),
                }),
                (_, None) => rules.flags.push(Rule {
                    subject,
                    level: FlagLevel::parse(&row.access_level),
                }),
                (_, Some(flag_id)) => rules.flag_objects.push((
                    flag_id,
                    Rule {
                        subject,
                        level: FlagLevel::parse(&row.access_level),
                    },
                )),
            }
        }
        Ok(Self::Rules(rules))
    }
}

impl AccessRules {
    fn allows_project(&self) -> bool {
        // A project has no resource-wide rules, so only its own rules and the default apply.
        object_level(&self.project, None, self.most_specific_order) >= ProjectLevel::Member
    }

    fn allows_flag_resource(&self) -> bool {
        let level =
            resource_level(&self.flags, self.most_specific_order).unwrap_or(FlagLevel::DEFAULT);
        level >= FlagLevel::Viewer
            || self.flag_objects.iter().any(|(_, rule)| {
                rule.subject != Subject::Everyone && rule.level >= FlagLevel::Viewer
            })
    }

    fn allows_flag(&self, flag_id: i32, created_by_id: Option<i32>) -> bool {
        if created_by_id == Some(self.user_id) {
            return true;
        }
        let flag_id = flag_id.to_string();
        let object: Vec<Rule<FlagLevel>> = self
            .flag_objects
            .iter()
            .filter(|(id, _)| *id == flag_id)
            .map(|(_, rule)| *rule)
            .collect();
        let resource = resource_level(&self.flags, self.most_specific_order);
        object_level(&object, resource, self.most_specific_order) >= FlagLevel::Viewer
    }
}

#[derive(FromRow)]
struct MembershipRow {
    membership_id: Uuid,
    organization_id: Uuid,
    level: i16,
    access_control: bool,
    role_based_access: bool,
    most_specific_order: bool,
}

#[derive(FromRow)]
struct RuleRow {
    resource: String,
    resource_id: Option<String>,
    access_level: String,
    is_member: bool,
    is_role: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use Subject::{Everyone, Member, Role};

    const USER_ID: i32 = 7;
    const FLAG_ID: i32 = 42;
    const OTHER_FLAG_ID: i32 = 43;

    fn rules(
        most_specific_order: bool,
        project: &[(Subject, &str)],
        flags: &[(Subject, &str)],
        flag_objects: &[(i32, Subject, &str)],
    ) -> AccessRules {
        AccessRules {
            user_id: USER_ID,
            most_specific_order,
            project: project
                .iter()
                .map(|&(subject, level)| Rule {
                    subject,
                    level: ProjectLevel::parse(level),
                })
                .collect(),
            flags: flags
                .iter()
                .map(|&(subject, level)| Rule {
                    subject,
                    level: FlagLevel::parse(level),
                })
                .collect(),
            flag_objects: flag_objects
                .iter()
                .map(|&(id, subject, level)| {
                    (
                        id.to_string(),
                        Rule {
                            subject,
                            level: FlagLevel::parse(level),
                        },
                    )
                })
                .collect(),
        }
    }

    #[rstest]
    #[case::no_rules(false, &[], true)]
    #[case::private_project(false, &[(Everyone, "none")], false)]
    #[case::private_project_member_added(false, &[(Everyone, "none"), (Member, "member")], true)]
    #[case::legacy_role_beats_member_none(false, &[(Member, "none"), (Role, "member")], true)]
    #[case::most_specific_member_none_beats_role(true, &[(Member, "none"), (Role, "member")], false)]
    #[case::unknown_level_denies(false, &[(Everyone, "owner")], false)]
    fn test_project_access(
        #[case] most_specific_order: bool,
        #[case] project: &[(Subject, &str)],
        #[case] expected: bool,
    ) {
        let access = FlagAccess::Rules(rules(most_specific_order, project, &[], &[]));
        assert_eq!(access.allows_flags(), expected);
    }

    #[rstest]
    #[case::no_rules(false, &[], &[], true)]
    #[case::resource_none(false, &[(Everyone, "none")], &[], false)]
    #[case::resource_none_with_grant_on_one_flag(false, &[(Everyone, "none")], &[(OTHER_FLAG_ID, Member, "viewer")], true)]
    #[case::resource_none_everyone_rule_on_one_flag(false, &[(Everyone, "none")], &[(OTHER_FLAG_ID, Everyone, "viewer")], false)]
    #[case::legacy_highest_rule_wins(false, &[(Everyone, "editor"), (Member, "none")], &[], true)]
    #[case::most_specific_member_rule_wins(true, &[(Everyone, "editor"), (Member, "none")], &[], false)]
    fn test_flag_resource_access(
        #[case] most_specific_order: bool,
        #[case] flags: &[(Subject, &str)],
        #[case] flag_objects: &[(i32, Subject, &str)],
        #[case] expected: bool,
    ) {
        let access = FlagAccess::Rules(rules(most_specific_order, &[], flags, flag_objects));
        assert_eq!(access.allows_flags(), expected);
    }

    #[rstest]
    #[case::no_rules(false, &[], &[], None, true)]
    #[case::private_flag(false, &[], &[(FLAG_ID, Everyone, "none")], None, false)]
    #[case::private_flag_most_specific(true, &[], &[(FLAG_ID, Everyone, "none")], None, false)]
    #[case::private_flag_shared_with_member(false, &[], &[(FLAG_ID, Everyone, "none"), (FLAG_ID, Member, "viewer")], None, true)]
    #[case::private_flag_creator(false, &[], &[(FLAG_ID, Everyone, "none")], Some(USER_ID), true)]
    #[case::private_other_flag(false, &[], &[(OTHER_FLAG_ID, Everyone, "none")], None, true)]
    #[case::legacy_resource_none_closes_everyone_rule(false, &[(Everyone, "none")], &[(FLAG_ID, Everyone, "viewer")], None, false)]
    #[case::most_specific_resource_none_closes_everyone_rule(true, &[(Everyone, "none")], &[(FLAG_ID, Everyone, "viewer")], None, false)]
    #[case::resource_none_member_rule_opens(true, &[(Everyone, "none")], &[(FLAG_ID, Member, "viewer")], None, true)]
    #[case::legacy_role_beats_member_none(false, &[], &[(FLAG_ID, Member, "none"), (FLAG_ID, Role, "viewer")], None, true)]
    #[case::most_specific_member_none_beats_role(true, &[], &[(FLAG_ID, Member, "none"), (FLAG_ID, Role, "viewer")], None, false)]
    fn test_flag_access(
        #[case] most_specific_order: bool,
        #[case] flags: &[(Subject, &str)],
        #[case] flag_objects: &[(i32, Subject, &str)],
        #[case] created_by_id: Option<i32>,
        #[case] expected: bool,
    ) {
        let access = FlagAccess::Rules(rules(most_specific_order, &[], flags, flag_objects));
        assert_eq!(access.allows_flag(FLAG_ID, created_by_id), expected);
    }

    #[test]
    fn test_no_membership_denies() {
        assert!(!FlagAccess::NoMembership.allows_flags());
        assert!(!FlagAccess::NoMembership.allows_flag(FLAG_ID, Some(USER_ID)));
    }
}

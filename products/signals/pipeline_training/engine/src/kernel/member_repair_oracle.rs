use anyhow::{anyhow, bail, Result};
use serde::Serialize;
use std::collections::{BTreeMap, HashMap, HashSet};

const MAX_DESCRIPTION_CHARS: usize = 1200;
const PROMPT_VERSION: &str = "remediation-coherence-v2";

#[derive(Clone)]
pub struct MemberEvidence {
    pub id: String,
    pub product: String,
    pub source_type: String,
    pub content: String,
    pub is_trigger: bool,
}

#[derive(Clone)]
struct EvidenceGroup {
    id: String,
    members: Vec<MemberEvidence>,
}

pub struct OraclePrompt {
    pub text: String,
    left_groups: HashMap<String, Vec<String>>,
    right_groups: HashMap<String, Vec<String>>,
}

#[derive(Clone, Serialize)]
pub struct OracleAudit {
    pub model: String,
    pub prompt_version: String,
    pub action: String,
    pub reason: String,
    pub confidence: String,
    pub selected_left: Vec<String>,
    pub selected_right: Vec<String>,
}

pub enum OracleChoice {
    Accept(OracleAudit),
    Reject(OracleAudit),
    Alternative(OracleAudit),
}

pub fn parse_json_text(text: &str) -> Result<serde_json::Value> {
    let start = text
        .find('{')
        .ok_or_else(|| anyhow!("response contains no JSON object"))?;
    let end = text
        .rfind('}')
        .ok_or_else(|| anyhow!("response contains no JSON object"))?;
    serde_json::from_str(&text[start..=end]).map_err(Into::into)
}

fn compact_description(value: &str) -> String {
    let normalized = value.split_whitespace().collect::<Vec<_>>().join(" ");
    let mut output = normalized
        .chars()
        .take(MAX_DESCRIPTION_CHARS)
        .collect::<String>();
    if normalized.chars().count() > MAX_DESCRIPTION_CHARS {
        output.push_str("...");
    }
    output
}

fn group_members(side: &str, members: &[MemberEvidence]) -> Vec<EvidenceGroup> {
    let mut grouped: BTreeMap<(String, String, String, bool), Vec<MemberEvidence>> =
        BTreeMap::new();
    for member in members {
        grouped
            .entry((
                member.product.clone(),
                member.source_type.clone(),
                member.content.clone(),
                member.is_trigger,
            ))
            .or_default()
            .push(member.clone());
    }
    let mut values = grouped.into_values().collect::<Vec<_>>();
    values.sort_by(|left, right| {
        right
            .len()
            .cmp(&left.len())
            .then(left[0].content.cmp(&right[0].content))
    });
    values
        .into_iter()
        .enumerate()
        .map(|(index, grouped_members)| EvidenceGroup {
            id: format!("{side}{}", index + 1),
            members: grouped_members,
        })
        .collect()
}

fn render_inventory(title: &str, groups: &[EvidenceGroup], proposed: &HashSet<String>) -> String {
    let total_members = groups
        .iter()
        .map(|group| group.members.len())
        .sum::<usize>();
    let mut lines = vec![format!(
        "{title}: {total_members} MEMBERS IN {} ATOMIC EVIDENCE GROUPS",
        groups.len()
    )];
    for group in groups {
        let exemplar = &group.members[0];
        let selected = group
            .members
            .iter()
            .filter(|member| proposed.contains(&member.id))
            .count();
        let trigger = group.members.iter().any(|member| member.is_trigger);
        let description = serde_json::to_string(&compact_description(&exemplar.content))
            .expect("serializing a string cannot fail");
        lines.push(format!(
            "{} COUNT={} SOURCE={}/{} TRIGGER={} PROPOSED_SELECTED={}/{} DESCRIPTION={}",
            group.id,
            group.members.len(),
            exemplar.product,
            exemplar.source_type,
            trigger,
            selected,
            group.members.len(),
            description,
        ));
    }
    lines.join("\n")
}

pub fn build_prompt(
    trigger_score: f64,
    left_members: Vec<MemberEvidence>,
    right_members: Vec<MemberEvidence>,
    proposed_left: &[String],
    proposed_right: &[String],
) -> OraclePrompt {
    let left_groups = group_members("L", &left_members);
    let right_groups = group_members("R", &right_members);
    let proposed_left = proposed_left.iter().cloned().collect::<HashSet<_>>();
    let proposed_right = proposed_right.iter().cloned().collect::<HashSet<_>>();
    let left_text = render_inventory(
        "LEFT REPORT (CURRENT JOIN WINNER)",
        &left_groups,
        &proposed_left,
    );
    let right_text = render_inventory("RIGHT REPORT (RUNNER-UP)", &right_groups, &proposed_right);
    let text = format!(
        r#"You are the final semantic oracle for one report-shuffling proposal.

One new signal has already been joined into the LEFT report. The learned join model also found the RIGHT report plausible, with runner-up score {trigger_score:.6}. A neural shuffler then proposed one cross-report member mask. PROPOSED_SELECTED=x/y on each evidence group shows how many members the neural mask selected.

Reports consolidate evidence about an underlying product problem. The unit of grouping is a shared investigation or remediation target, not one symptom, exception, call site, component, narrowly phrased pull request, or currently known fix.

Group signals when they are reasonably likely to be different manifestations of the same defect, causal mechanism, affected user journey, or remediation effort. One underlying problem may appear through different symptoms, signal types, exception classes, code paths, or components. It may initially appear to require several changes. If investigating the signals together would help an engineer discover and resolve their shared cause, they belong together.

Separate signals only when there is affirmative evidence that they are independent problems whose causes, resolution, or validation would be handled separately. Shared product area, generic symptom, sentiment, exception class, or vocabulary alone is not sufficient to group them. However, uncertainty about the exact root cause is not itself a reason to split: do not require proof of a shared cause when it is a credible explanation supported by the evidence.

Duplicate reports are costly because they fragment evidence and can cause duplicate investigations or pull requests. Do not split one underlying issue merely because each manifestation could receive its own narrow issue title. When both interpretations remain plausible, prefer preserving a useful shared investigation over creating near-duplicate reports, while still rejecting combinations that would obscure genuinely independent problems.

Judge the complete inventories, not just the trigger signal.

Choose exactly one action:
- accept: the neural mask identifies one remediation-coherent cross-report set and applying it is better than leaving the reports unchanged.
- reject: no safe useful cross-report operation is justified, or the neural proposal would mix distinct concerns. This leaves the post-join reports unchanged.
- alternative: one different remediation-coherent cross-report member mask is clearly better. Return the LEFT and RIGHT atomic evidence group IDs for one shared investigation or remediation target. Selecting a group selects every member represented by that group. The alternative must include at least one group from each side. It may select all groups on one or both sides.

Do not return multiple components. If several unrelated shared problems exist, choose alternative only when one is clearly the most useful immediate consolidation; otherwise reject. Infer shared causes reasonably from the supplied evidence, but do not invent unsupported connections merely to reduce report count.

Return only JSON:
{{
  "action": "accept" | "reject" | "alternative",
  "left_groups": ["L1"],
  "right_groups": ["R2"],
  "reason": "brief semantic boundary explanation",
  "confidence": "high" | "medium" | "low"
}}

For accept or reject, left_groups and right_groups must be empty arrays.

{left_text}

{right_text}"#
    );
    OraclePrompt {
        text,
        left_groups: left_groups
            .into_iter()
            .map(|group| {
                (
                    group.id,
                    group.members.into_iter().map(|member| member.id).collect(),
                )
            })
            .collect(),
        right_groups: right_groups
            .into_iter()
            .map(|group| {
                (
                    group.id,
                    group.members.into_iter().map(|member| member.id).collect(),
                )
            })
            .collect(),
    }
}

fn string_array(value: &serde_json::Value, key: &str) -> Result<Vec<String>> {
    value
        .get(key)
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| anyhow!("{key} must be an array"))?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .ok_or_else(|| anyhow!("{key} entries must be strings"))
        })
        .collect()
}

fn expand_groups(
    groups: &[String],
    inventory: &HashMap<String, Vec<String>>,
    side: &str,
) -> Result<Vec<String>> {
    let mut seen = HashSet::new();
    let mut selected = Vec::new();
    for group in groups {
        if !seen.insert(group) {
            bail!("{side} group {group} is repeated");
        }
        let members = inventory
            .get(group)
            .ok_or_else(|| anyhow!("unknown {side} group {group}"))?;
        selected.extend(members.iter().cloned());
    }
    Ok(selected)
}

pub fn parse_response(
    value: &serde_json::Value,
    model: &str,
    prompt: &OraclePrompt,
    proposed_left: &[String],
    proposed_right: &[String],
) -> Result<OracleChoice> {
    let action = value
        .get("action")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| anyhow!("action must be a string"))?
        .to_ascii_lowercase();
    let reason = value
        .get("reason")
        .and_then(serde_json::Value::as_str)
        .filter(|reason| !reason.trim().is_empty())
        .ok_or_else(|| anyhow!("reason must be a non-empty string"))?
        .to_string();
    let confidence = value
        .get("confidence")
        .and_then(serde_json::Value::as_str)
        .filter(|confidence| matches!(*confidence, "high" | "medium" | "low"))
        .ok_or_else(|| anyhow!("confidence must be high, medium, or low"))?
        .to_string();
    let left_groups = string_array(value, "left_groups")?;
    let right_groups = string_array(value, "right_groups")?;
    let audit =
        |action: &str, selected_left: Vec<String>, selected_right: Vec<String>| OracleAudit {
            model: model.to_string(),
            prompt_version: PROMPT_VERSION.to_string(),
            action: action.to_string(),
            reason: reason.clone(),
            confidence: confidence.clone(),
            selected_left,
            selected_right,
        };
    match action.as_str() {
        "accept" => {
            if !left_groups.is_empty() || !right_groups.is_empty() {
                bail!("accept must not return alternative groups");
            }
            if proposed_left.is_empty() || proposed_right.is_empty() {
                bail!("cannot accept a one-sided neural mask");
            }
            Ok(OracleChoice::Accept(audit(
                "accept",
                proposed_left.to_vec(),
                proposed_right.to_vec(),
            )))
        }
        "reject" => {
            if !left_groups.is_empty() || !right_groups.is_empty() {
                bail!("reject must not return alternative groups");
            }
            Ok(OracleChoice::Reject(audit(
                "reject",
                Vec::new(),
                Vec::new(),
            )))
        }
        "alternative" => {
            if left_groups.is_empty() || right_groups.is_empty() {
                bail!("alternative must select at least one group from each side");
            }
            let selected_left = expand_groups(&left_groups, &prompt.left_groups, "left")?;
            let selected_right = expand_groups(&right_groups, &prompt.right_groups, "right")?;
            Ok(OracleChoice::Alternative(audit(
                "alternative",
                selected_left,
                selected_right,
            )))
        }
        _ => bail!("unknown action {action}"),
    }
}

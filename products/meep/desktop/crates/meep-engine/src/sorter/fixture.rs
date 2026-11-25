use super::*;
/// Test sorter driven by explicit fixture attributes.
#[derive(Default)]
pub struct FixtureSorter;
#[async_trait]
impl Sorter for FixtureSorter {
    async fn check_facts(&self, input: FactCheckInput<'_>) -> Result<Vec<FactVerdict>> {
        Ok(vec![FactVerdict::Independent; input.candidates.len()])
    }
    async fn sort(&self, input: SortInput<'_>) -> Result<Sorted> {
        let data = &input.event.attributes;
        let summary = input.thread.subject.clone();
        let rule = meep_policy::skip_candidates(&input.topic.rules, input.message).next();
        let decision = if data["skip"] == true
            && let Some(rule) = rule
        {
            Decision::Skip {
                reason: rule.text.clone(),
                rule: Some(rule.id),
            }
        } else if data["needs_decision"] == true {
            Decision::Ask {
                summary: summary.clone(),
                reason: "Scripted review".into(),
                suggestions: vec![
                    Suggestion::DraftReply {
                        draft: data["draft"].as_str().unwrap_or("Draft").into(),
                        task_title: format!("Reply to {}", input.message.author),
                    },
                    Suggestion::MakeTask { title: summary },
                    Suggestion::Leave,
                ],
            }
        } else {
            Decision::Handle {
                summary,
                outcomes: vec![],
            }
        };
        Ok(Sorted {
            confidence: Some(1.0),
            decision,
            work: None,
            fact: data["fact"].as_str().map(str::to_owned),
        })
    }
    async fn thread(&self, _: &SortInput<'_>, _: &[&Thread]) -> Result<Option<ThreadId>> {
        Ok(None)
    }
}

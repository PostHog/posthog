//! The mounted native workflow host shares the view's live engine and data.
use super::*;
use meep_workflows::{
    Workflow,
    runner::{self, Control, Host, LocalFuture},
};

struct MountedHost {
    shared: Rc<Shared>,
    view: WeakEntity<ScriptView>,
    cx: RefCell<AsyncApp>,
    context: ViewContext,
    epoch: u64,
    group: Option<String>,
    control: Control,
    run_id: Value,
    generations: Rc<RefCell<HashMap<String, u64>>>,
    generation: Option<(String, u64)>,
}
impl MountedHost {
    fn changed(&self) -> Result<(), String> {
        self.control.check()?;
        self.view
            .update(&mut *self.cx.borrow_mut(), |view, cx| {
                if view.epoch != self.epoch || view.context.is_retired() {
                    self.control.cancel();
                    return Err("Workflow cancelled: view reloaded".into());
                }
                let previous = view.context.background_request();
                view.context.set_background_request(self.group.clone());
                view.after_js(cx, false);
                view.context.set_background_request(previous);
                Ok(())
            })
            .map_err(|e| e.to_string())?
    }
}
impl Host for MountedHost {
    fn progress(&self, workflow: &str, trace: &Value) {
        // Fire and forget: progress is drawn, never awaited.
        let _ = self.context.request(
            "native.workflows.progress",
            json!({"id":workflow,"run":self.run_id,"trace":trace}),
        );
    }
    fn current(&self) -> bool {
        self.generation
            .as_ref()
            .is_none_or(|(group, token)| self.generations.borrow().get(group) == Some(token))
    }
    fn expression(
        &self,
        code: String,
        input: Value,
    ) -> LocalFuture<'_, Result<meep_workflows::expressions::Evaluation, String>> {
        let cancelled = self.control.cancelled.clone();
        let task = self.context.runtime.spawn_blocking(move || {
            meep_workflows::expressions::evaluate(&code, input, Some(cancelled))
        });
        Box::pin(async move { task.await.map_err(|e| e.to_string())? })
    }
    fn state(&self) -> Result<Value, String> {
        self.control.check()?;
        self.shared.engine.checkpoint()
    }
    fn patch(&self, value: Value) -> Result<(), String> {
        self.control.check()?;
        self.shared.engine.workflow_patch(&value)?;
        self.changed()
    }
    fn data(&self, op: &str, table: &str, args: Value) -> Result<Value, String> {
        self.control.check()?;
        let result = self
            .shared
            .engine
            .data
            .borrow_mut()
            .request(op, table, &args)?;
        if ["set", "patch", "remove", "clear"].contains(&op) {
            // Dataset changes have no JS dirty callback.
            self.shared.engine.workflow_patch(&json!({}))?;
            self.changed()?;
        }
        Ok(result)
    }
    fn transform(&self, name: &str, args: Value) -> Result<Value, String> {
        self.control.check()?;
        self.shared.engine.workflow_transform(name, &args)
    }
    fn request(
        &self,
        method: &str,
        mut params: Value,
    ) -> LocalFuture<'_, Result<Value, crate::sdk::HostError>> {
        // Step params come from the script's workflow definition.
        super::strip_reserved(&mut params);
        if let Some(group) = &self.group {
            if params.is_null() {
                params = json!({});
            }
            let Some(fields) = params.as_object_mut() else {
                return Box::pin(async {
                    Err("Workflow request arguments must be an object".into())
                });
            };
            fields.insert("_background_request".into(), json!(group));
        }
        let rx = self
            .context
            .request_cancellable(method, params, self.control.cancelled.clone());
        Box::pin(async move {
            rx.recv()
                .await
                .map_err(|_| crate::sdk::HostError::from("Workflow request dropped"))?
        })
    }
}
impl ScriptView {
    pub(super) fn start_native_workflow(
        &mut self,
        id: u32,
        params: Value,
        group: Option<String>,
        cx: &mut Context<Self>,
    ) -> async_channel::Receiver<Result<Value, String>> {
        let (tx, rx) = async_channel::bounded(1);
        let definition = match Workflow::parse(params["definition"].clone()) {
            Ok(definition) if definition.version == 2 => definition,
            Ok(_) => {
                let _ = tx.try_send(Err("Native execution requires workflow version 2".into()));
                return rx;
            }
            Err(error) => {
                let _ = tx.try_send(Err(error.to_string()));
                return rx;
            }
        };
        let shared = self.shared.clone();
        let context = self.context.clone();
        let epoch = self.epoch;
        let control = Control::default();
        let generations = self.workflow_generations.clone();
        let generation = definition.generation.as_ref().map(|group| {
            let mut groups = generations.borrow_mut();
            let token = groups.entry(group.clone()).or_default();
            *token += 1;
            (group.clone(), *token)
        });
        self.native_workflows.insert(id, control.clone());
        cx.spawn(async move |view, cx| {
            let host = MountedHost {
                shared,
                view,
                cx: RefCell::new(cx.clone()),
                context,
                epoch,
                group,
                control: control.clone(),
                run_id: params["run"].clone(),
                generations,
                generation,
            };
            let run =
                runner::run(&host, &definition, params["input"].clone(), control.clone()).await;
            if control.check().is_err() && params["run"].is_string() {
                // restore_state drops the JS continuation that normally sends
                // finish. Tracking must outlive that continuation/control token.
                let saved = host.context.request("native.workflows.finish", json!({
                    "id":definition.id,"run":params["run"],"error":"Workflow cancelled: view reloaded"
                })).recv().await.unwrap_or_else(|_| Err("The host disconnected".into()));
                if let Err(error) = saved {
                    eprintln!("Could not record the cancelled workflow: {error}");
                }
            }
            if control.check().is_ok() && let Err(error) = host
                    .request(
                        "native.workflows.trace",
                        json!({"id":definition.id,"run":params["run"],"trace":run.trace}),
                    )
                    .await {
                eprintln!("Could not save the workflow trace: {error}");
            }
            let _ = tx.send(run.result).await;
        })
        .detach();
        rx
    }
}
impl Drop for MountedHost {
    fn drop(&mut self) {
        self.control.cancel();
    }
}
impl Drop for ScriptView {
    fn drop(&mut self) {
        for control in self.native_workflows.values() {
            control.cancel();
        }
    }
}

impl Build {
    pub(super) fn workflow_editor(
        &self,
        node: &Rc<Node>,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        use meep_workflow_ui::editor::{CodeEditor, Request, Target};
        if self.read_only {
            return ui::caption("This workflow is read-only.").into_any_element();
        }
        let owner = self.weak.clone();
        self.register_late(&node.key, &node.p);
        let definition = &node.p["definition"];
        let id = definition["id"].as_str().unwrap_or_default();
        let step = node.p["step"].as_str();
        let editor = window.use_keyed_state(
            ElementId::Name(format!("{}:{}:editor:{id}:{step:?}", self.scope, node.key).into()),
            cx,
            |window, cx| {
                let (weak, shared, key) =
                    (self.weak.clone(), self.shared.clone(), node.key.clone());
                CodeEditor::new(
                    Rc::new(move |req, cx| {
                        let Some(view) = owner.upgrade() else {
                            return Box::pin(async { Err("Workflow view closed".into()) });
                        };
                        let context = view.read(cx).context.clone();
                        Box::pin(async move {
                            match req {
                                Request::Save {
                                    expected,
                                    definition,
                                } => context
                                    .request(
                                        "native.workflows.update",
                                        json!({ "expected":expected,"definition":definition }),
                                    )
                                    .recv()
                                    .await
                                    .map_err(|_| "Workflow host closed".to_owned())?,
                                Request::Preview { code, input } => context
                                    .runtime
                                    .spawn_blocking(move || {
                                        meep_workflows::expressions::evaluate(&code, input, None)
                                            .map(|output| json!(output))
                                    })
                                    .await
                                    .map_err(|e| e.to_string())?,
                                _ => Err("This editor manages the workflow definition.".into()),
                            }
                        })
                    }),
                    definition.clone(),
                    step.map_or(Target::Definition, |step| Target::Step(step.to_owned())),
                    Rc::new(move |cx| {
                        if let Some(callback) = shared.late(&key, "onClose") {
                            let _ = weak.update(cx, |view, cx| {
                                view.invoke(callback, Value::Null, true, cx)
                            });
                        }
                    }),
                    window,
                    cx,
                )
            },
        );
        style(div().size_full().min_h_0().min_w_0().child(editor), node).into_any_element()
    }
}

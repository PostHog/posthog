use std::future::Future;

use crate::types::{
    operator::Operator,
    stage::{Stage, StageResult},
};

pub struct Batch<T>(Vec<T>);

impl<T> IntoIterator for Batch<T> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<Self::Item>;

    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}

impl<T> From<Vec<T>> for Batch<T> {
    fn from(vec: Vec<T>) -> Self {
        Batch(vec)
    }
}

impl<T> From<Batch<T>> for Vec<T> {
    fn from(batch: Batch<T>) -> Self {
        batch.0
    }
}

impl<T> Batch<T> {
    pub fn inner_ref(&self) -> &Vec<T> {
        &self.0
    }

    pub fn apply_func<Ctx, O, F, Fu, E>(
        self,
        mut func: F,
        ctx: Ctx,
    ) -> impl Future<Output = Result<Batch<O>, E>>
    where
        Ctx: Clone + Send,
        F: FnMut(T, Ctx) -> Fu + 'static,
        Fu: Future<Output = Result<O, E>> + Send + 'static,
        O: Send + 'static,
        E: Send + 'static,
    {
        let mut handles = vec![];
        for item in self.0.into_iter() {
            let future = func(item, ctx.clone());
            handles.push(tokio::spawn(future));
        }
        async move {
            futures::future::try_join_all(handles)
                .await
                .unwrap_or_else(|e| panic!("task panicked during batch processing: {:?}", e))
                .into_iter()
                .collect::<Result<Vec<_>, _>>()
                .map(|value| value.into())
        }
    }

    #[allow(clippy::manual_async_fn)]
    pub fn apply_operator<C, Op>(
        self,
        operator: Op,
        ctx: Op::Context,
    ) -> impl Future<Output = Result<Batch<Op::Input>, Op::Error>>
    where
        T: Send + 'static,
        C: Clone + Send + 'static,
        Op: Operator<Input = T, Output = T, Context = C> + Clone + Send + Sync + 'static,
    {
        async {
            let time = common_metrics::timing_guard(operator.name(), &[]);
            let res = self
                .apply_func(
                    move |item, ctx| {
                        let cloned_operator = operator.clone();
                        async move { cloned_operator.execute(item, ctx).await }
                    },
                    ctx,
                )
                .await?;
            time.label("outcome", "success");
            Ok(res)
        }
    }

    #[allow(clippy::manual_async_fn)]
    pub fn apply_stage<S>(self, stage: S) -> impl Future<Output = StageResult<S>>
    where
        S: Stage<Input = T>,
    {
        async {
            let time = common_metrics::timing_guard(stage.name(), &[]);
            let res = stage.process(self).await?;
            time.label("outcome", "success");
            Ok(res)
        }
    }
}

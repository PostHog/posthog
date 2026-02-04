use std::future::Future;

use crate::{
    error::UnhandledError,
    types::{operator::Operator, stage::Stage},
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
    pub fn apply_func<Ctx, O, F, Fu, E>(
        self,
        func: F,
        ctx: Ctx,
    ) -> impl Future<Output = Result<Batch<O>, E>>
    where
        Ctx: Clone + Send,
        F: Fn(T, Ctx) -> Fu + 'static,
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
                .expect("failed to join tasks")
                .into_iter()
                .collect::<Result<Vec<_>, _>>()
                .map(|value| value.into())
        }
    }

    pub fn apply_operator<C, Op>(
        self,
        operator: Op,
        ctx: Op::Context,
    ) -> impl Future<Output = Result<Batch<Op::Item>, Op::Error>>
    where
        T: Send + 'static,
        C: Clone + Send + 'static,
        Op: Operator<Item = T, Context = C> + Clone + Send + Sync + 'static,
    {
        self.apply_func(
            move |item, ctx| {
                let cloned_operator = operator.clone();
                async move { cloned_operator.execute(item, ctx).await }
            },
            ctx,
        )
    }

    pub fn apply_stage<S>(
        self,
        stage: S,
    ) -> impl Future<Output = Result<Batch<S::Item>, UnhandledError>>
    where
        S: Stage<Item = T> + 'static,
    {
        stage.process(self)
    }
}

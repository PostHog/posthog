use std::future::Future;

use crate::{
    error::UnhandledError,
    types::{
        operator::{Operator, OperatorContext},
        stage::Stage,
    },
};

impl<I: IntoIterator<Item = T>, T> Batch<T> for I {}

pub trait Batch<T>: Sized + IntoIterator<Item = T> {
    async fn process_sequential<O, F, Fu>(self, func: F) -> Result<Vec<O>, UnhandledError>
    where
        F: Fn(T) -> Fu,
        Fu: Future<Output = Result<O, UnhandledError>>,
    {
        let mut results = Vec::new();
        let iterator = self.into_iter();
        for item in iterator {
            results.push(func(item).await?);
        }
        Ok(results)
    }

    async fn process_concurrent<O, F, Fu>(self, func: F) -> Result<Vec<O>, UnhandledError>
    where
        F: FnMut(T) -> Fu,
        Fu: Future<Output = Result<O, UnhandledError>>,
    {
        let futures = self.into_iter().map(func);
        let results = futures::future::try_join_all(futures).await?;
        Ok(results)
    }

    async fn spawn<C, O, F, Fu>(self, mut func: F, ctx: &C) -> Result<Vec<O>, UnhandledError>
    where
        C: Clone,
        F: FnMut(T, C) -> Fu,
        Fu: Future<Output = Result<O, UnhandledError>> + Send + 'static,
        O: Send + 'static,
    {
        let mut handles = vec![];
        for item in self.into_iter() {
            let future = func(item, ctx.clone());
            handles.push(tokio::spawn(future));
        }
        futures::future::try_join_all(handles)
            .await
            .expect("failed to join tasks")
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
    }

    async fn map<
        O: Send + 'static,
        C: OperatorContext + Clone + 'static,
        Op: Operator<C, Input = T, Output = O> + Clone + Send + 'static,
    >(
        self,
        operator: Op,
        ctx: &C,
    ) -> Result<impl Batch<O>, UnhandledError>
    where
        T: Send + 'static,
    {
        let cloned_op = operator.clone();
        self.spawn(
            |item, ctx| {
                let cloned_op = cloned_op.clone();
                async move { cloned_op.clone().execute(item, &ctx).await }
            },
            ctx,
        )
        .await
    }

    async fn map_all<S: Stage<Item = T> + 'static>(
        self,
        stage: &S,
    ) -> Result<impl Batch<T>, UnhandledError>
    where
        T: Send + 'static,
    {
        stage.process(self).await
    }
}

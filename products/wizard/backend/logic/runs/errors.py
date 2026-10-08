class WizardRunDispatchError(Exception):
    def __init__(self, *, is_exhausted: bool) -> None:
        self.exhausted = is_exhausted
        super().__init__()


class WizardWorkerCleanupError(Exception):
    pass

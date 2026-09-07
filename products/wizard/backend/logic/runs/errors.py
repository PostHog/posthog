class WizardRunDispatchError(Exception):
    def __init__(self, *, exhausted: bool) -> None:
        self.exhausted = exhausted
        super().__init__()


class WizardWorkerCleanupError(Exception):
    pass

class InvalidWizardVersionError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid Wizard version")


class InvalidWizardProgramCommandError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid Wizard program command")

class SmartDiagnostError(Exception):
    """Base class for errors that are safe to show to the user."""


class ValidationError(SmartDiagnostError):
    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("\n".join(self.errors))


class AuthError(SmartDiagnostError):
    pass


class PermissionDenied(SmartDiagnostError):
    def __init__(self, message="Бұл әрекетке рұқсатыңыз жоқ."):
        super().__init__(message)


class NotFound(SmartDiagnostError):
    def __init__(self, message="Жазба табылмады."):
        super().__init__(message)

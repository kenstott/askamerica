class AskAmericaError(Exception):
    pass


class AuthError(AskAmericaError):
    pass


class EngineNotInstalledError(AskAmericaError):
    pass


class QuotaExceededError(AskAmericaError):
    def __init__(self, remaining_bytes: int, period: str, upgrade_url: str = None):
        self.remaining_bytes = remaining_bytes
        self.period = period
        self.upgrade_url = upgrade_url or "https://askamerica.ai/upgrade"
        super().__init__(
            f"Monthly quota exceeded for {period}. "
            f"Upgrade at {self.upgrade_url}"
        )


class QueryError(AskAmericaError):
    pass

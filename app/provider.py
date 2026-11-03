FAIL_ABOVE_MINOR = 500_000


def charge(amount_minor: int, idempotency_key: str) -> tuple[str, str]:
    status = "FAILED" if amount_minor > FAIL_ABOVE_MINOR else "SUCCEEDED"
    return status, f"mock_{idempotency_key}"

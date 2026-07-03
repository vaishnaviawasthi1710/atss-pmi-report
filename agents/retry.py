import time

_RETRYABLE_MARKERS = ("RESOURCE_EXHAUSTED", "429", "UNAVAILABLE", "503")


def generate_content_with_retry(client, max_retries: int = 2, backoff_base: float = 2.0, **kwargs):
    """
    Wraps client.models.generate_content(**kwargs) with a short exponential
    backoff retry on rate-limit / transient-unavailability errors.

    Gemini's free tier has a low requests-per-minute ceiling, so a burst of
    calls (e.g. captioning several photos back to back) can trip a 429 that
    clears within a few seconds. Retrying absorbs that instead of failing
    on the first hit. A genuinely exhausted daily/project quota will still
    fail every retry and surface to the caller as before — this only
    smooths over the transient case.
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return client.models.generate_content(**kwargs)
        except Exception as e:
            last_err = e
            msg = str(e)
            is_retryable = any(marker in msg for marker in _RETRYABLE_MARKERS)
            if not is_retryable or attempt == max_retries:
                raise
            time.sleep(backoff_base * (2 ** attempt))
    raise last_err

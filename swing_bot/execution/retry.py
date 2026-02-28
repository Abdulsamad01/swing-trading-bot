"""
Retry wrapper with exponential backoff and jitter.
Used for all exchange API calls.
"""

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    jitter_percent: float = 20.0,
    label: str = "",
) -> T:
    """
    Call fn() with exponential backoff retries.

    Parameters
    ----------
    fn            : callable that may raise an exception
    max_retries   : number of retries after first failure
    base_delay    : initial delay in seconds (doubles each retry)
    jitter_percent: random jitter ±% applied to delay
    label         : descriptive name for logging

    Returns
    -------
    Return value of fn() on success.

    Raises
    ------
    Last exception if all retries exhausted.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt == max_retries:
                logger.error(f"[{label}] Failed after {max_retries + 1} attempts: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            jitter = delay * (jitter_percent / 100.0) * (2 * random.random() - 1)
            sleep_time = max(0.1, delay + jitter)
            logger.warning(
                f"[{label}] Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {sleep_time:.2f}s..."
            )
            time.sleep(sleep_time)

    raise last_exc

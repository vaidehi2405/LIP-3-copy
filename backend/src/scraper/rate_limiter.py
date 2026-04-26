"""
Rate Limiter with Exponential Backoff and Jitter

Provides request throttling to respect platform rate limits and
automatic retry with exponential backoff on transient failures (429, 503, timeouts).
"""

import time
import random
import structlog
from typing import Callable, Any, Optional

logger = structlog.get_logger(__name__)


class RateLimitError(Exception):
    """Raised when all retries are exhausted after rate limiting."""

    def __init__(self, message: str, last_status_code: Optional[int] = None):
        super().__init__(message)
        self.last_status_code = last_status_code


class RateLimiter:
    """
    Rate limiter that enforces requests-per-minute limits and
    handles retries with exponential backoff + jitter.

    Usage:
        limiter = RateLimiter(requests_per_minute=10, retry_max=3, retry_backoff_seconds=5)
        result = limiter.execute(lambda: requests.get(url))
    """

    def __init__(
        self,
        requests_per_minute: int = 10,
        retry_max: int = 3,
        retry_backoff_seconds: float = 5.0,
    ):
        self.min_interval = 60.0 / requests_per_minute
        self.retry_max = retry_max
        self.retry_backoff_seconds = retry_backoff_seconds
        self._last_request_time: float = 0.0
        self._request_count: int = 0
        self._retry_count: int = 0

    def _wait_for_rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logger.debug("rate_limit_wait", sleep_seconds=round(sleep_time, 2))
            time.sleep(sleep_time)
        self._last_request_time = time.monotonic()

    def _backoff_with_jitter(self, attempt: int) -> float:
        """Calculate backoff time with jitter for a given retry attempt."""
        # Exponential backoff: base * 2^attempt
        backoff = self.retry_backoff_seconds * (2 ** attempt)
        # Add jitter: random factor between 0.5x and 1.5x
        jitter = backoff * (0.5 + random.random())
        return jitter

    def execute(
        self,
        func: Callable[[], Any],
        retryable_status_codes: tuple = (429, 503),
    ) -> Any:
        """
        Execute a function with rate limiting and retry logic.

        Args:
            func: Callable that makes the request. Should return a response
                  object with a `status_code` attribute, or raise an exception.
            retryable_status_codes: HTTP status codes that trigger a retry.

        Returns:
            The result of func() on success.

        Raises:
            RateLimitError: If all retries are exhausted.
        """
        last_error = None

        for attempt in range(self.retry_max + 1):
            self._wait_for_rate_limit()
            self._request_count += 1

            try:
                result = func()

                # Check if result has a status_code (e.g., requests.Response)
                status_code = getattr(result, "status_code", None)
                if status_code and status_code in retryable_status_codes:
                    last_error = RateLimitError(
                        f"HTTP {status_code}", last_status_code=status_code
                    )
                    if attempt < self.retry_max:
                        wait = self._backoff_with_jitter(attempt)
                        logger.warning(
                            "retryable_status_code",
                            status_code=status_code,
                            attempt=attempt + 1,
                            max_retries=self.retry_max,
                            backoff_seconds=round(wait, 2),
                        )
                        self._retry_count += 1
                        time.sleep(wait)
                        continue
                    else:
                        raise last_error

                return result

            except RateLimitError:
                raise

            except Exception as e:
                last_error = e
                if attempt < self.retry_max:
                    wait = self._backoff_with_jitter(attempt)
                    logger.warning(
                        "request_error_retry",
                        error=str(e),
                        error_type=type(e).__name__,
                        attempt=attempt + 1,
                        max_retries=self.retry_max,
                        backoff_seconds=round(wait, 2),
                    )
                    self._retry_count += 1
                    time.sleep(wait)
                else:
                    logger.error(
                        "request_error_exhausted",
                        error=str(e),
                        error_type=type(e).__name__,
                        total_attempts=self.retry_max + 1,
                    )
                    raise RateLimitError(
                        f"All {self.retry_max} retries exhausted. Last error: {e}"
                    ) from e

        # Should not reach here, but just in case
        raise RateLimitError(f"Unexpected state after {self.retry_max + 1} attempts")

    @property
    def stats(self) -> dict:
        """Return rate limiter statistics."""
        return {
            "total_requests": self._request_count,
            "total_retries": self._retry_count,
        }

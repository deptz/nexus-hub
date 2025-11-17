"""Enhanced error handling with retry logic and granular error types."""

import asyncio
import time
from typing import Optional, Type, Tuple, Callable, Any
from enum import Enum


class ErrorCategory(str, Enum):
    """Categories of errors for better handling."""
    NETWORK = "network"  # Connection issues, timeouts
    API_ERROR = "api_error"  # API returned error response
    AUTH_ERROR = "auth_error"  # Authentication/authorization failures
    RATE_LIMIT = "rate_limit"  # Rate limit exceeded
    VALIDATION = "validation"  # Input validation errors
    BUSINESS_LOGIC = "business_logic"  # Business rule violations
    UNKNOWN = "unknown"  # Unknown errors


class RetryableError(Exception):
    """Base exception for retryable errors."""
    def __init__(self, message: str, category: ErrorCategory, retryable: bool = True, retry_after: Optional[float] = None):
        self.message = message
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(message)


class NetworkError(RetryableError):
    """Network-related errors (connection, timeout)."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message, ErrorCategory.NETWORK, retryable=True, retry_after=retry_after)


class APIError(RetryableError):
    """API returned an error response."""
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False, retry_after: Optional[float] = None):
        self.status_code = status_code
        super().__init__(message, ErrorCategory.API_ERROR, retryable=retryable, retry_after=retry_after)


class AuthError(RetryableError):
    """Authentication/authorization errors."""
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.AUTH_ERROR, retryable=False)


class RateLimitError(RetryableError):
    """Rate limit exceeded."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message, ErrorCategory.RATE_LIMIT, retryable=True, retry_after=retry_after)


class ValidationError(RetryableError):
    """Input validation errors."""
    def __init__(self, message: str):
        super().__init__(message, ErrorCategory.VALIDATION, retryable=False)


def classify_error(error: Exception) -> Tuple[ErrorCategory, bool, Optional[float]]:
    """
    Classify an error into a category and determine if it's retryable.
    
    Args:
        error: The exception to classify
    
    Returns:
        Tuple of (category, retryable, retry_after_seconds)
    """
    if isinstance(error, RetryableError):
        return error.category, error.retryable, error.retry_after
    
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Network errors
    if any(keyword in error_str for keyword in ['connection', 'timeout', 'network', 'dns', 'refused']):
        return ErrorCategory.NETWORK, True, None
    
    if error_type in ['ConnectionError', 'TimeoutError', 'asyncio.TimeoutError']:
        return ErrorCategory.NETWORK, True, None
    
    # Rate limit errors
    if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
        # Try to extract retry_after from error
        retry_after = None
        if 'retry-after' in error_str:
            # Simple extraction - could be enhanced
            try:
                import re
                match = re.search(r'retry[_-]after[:\s]+(\d+)', error_str, re.IGNORECASE)
                if match:
                    retry_after = float(match.group(1))
            except:
                pass
        return ErrorCategory.RATE_LIMIT, True, retry_after
    
    # Auth errors
    if any(keyword in error_str for keyword in ['unauthorized', 'forbidden', '401', '403', 'authentication', 'authorization']):
        return ErrorCategory.AUTH_ERROR, False, None
    
    # API errors (non-retryable by default)
    if 'api' in error_str or 'http' in error_str:
        return ErrorCategory.API_ERROR, False, None
    
    return ErrorCategory.UNKNOWN, False, None


async def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Any:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exception types to retry
        on_retry: Optional callback called on each retry (exception, attempt_number)
    
    Returns:
        Result of the function call
    
    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_exception = e
            
            # Check if error is retryable
            category, retryable, retry_after = classify_error(e)
            
            if not retryable:
                raise
            
            if attempt < max_retries:
                # Calculate delay
                if retry_after:
                    delay = min(retry_after, max_delay)
                else:
                    delay = min(initial_delay * (exponential_base ** attempt), max_delay)
                
                # Add jitter to avoid thundering herd
                import random
                jitter = random.uniform(0, delay * 0.1)
                delay += jitter
                
                if on_retry:
                    # Handle both sync and async callbacks
                    result = on_retry(e, attempt + 1)
                    if asyncio.iscoroutine(result):
                        await result
                
                await asyncio.sleep(delay)
            else:
                # Last attempt failed
                raise
    
    # Should never reach here, but just in case
    if last_exception:
        raise last_exception


def wrap_llm_error(error: Exception, provider: str) -> RetryableError:
    """
    Wrap LLM API errors into our error types.
    
    Args:
        error: Original exception
        provider: LLM provider name ('openai', 'gemini')
    
    Returns:
        RetryableError with appropriate category
    """
    error_str = str(error)
    error_lower = error_str.lower()
    
    # Check for rate limit
    if 'rate limit' in error_lower or '429' in error_str:
        retry_after = None
        # Try to extract from headers if available
        if hasattr(error, 'response') and hasattr(error.response, 'headers'):
            retry_after_header = error.response.headers.get('retry-after')
            if retry_after_header:
                try:
                    retry_after = float(retry_after_header)
                except:
                    pass
        return RateLimitError(f"{provider} rate limit exceeded", retry_after=retry_after)
    
    # Check for auth errors
    if '401' in error_str or 'unauthorized' in error_lower or 'authentication' in error_lower:
        return AuthError(f"{provider} authentication failed: {error_str}")
    
    # Check for network errors
    if any(keyword in error_lower for keyword in ['connection', 'timeout', 'network']):
        return NetworkError(f"{provider} network error: {error_str}")
    
    # Check for API errors
    if hasattr(error, 'status_code'):
        status_code = error.status_code
        if status_code == 429:
            return RateLimitError(f"{provider} rate limit exceeded (429)")
        elif status_code in [401, 403]:
            return AuthError(f"{provider} auth error ({status_code})")
        elif status_code >= 500:
            # Server errors are retryable
            return APIError(f"{provider} server error ({status_code})", status_code=status_code, retryable=True)
        else:
            return APIError(f"{provider} API error ({status_code})", status_code=status_code, retryable=False)
    
    # Default to network error for unknown errors (assume retryable)
    return NetworkError(f"{provider} error: {error_str}")


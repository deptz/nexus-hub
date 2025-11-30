"""Circuit breaker for external service calls."""

from enum import Enum
from typing import Callable, Any, Optional
from datetime import datetime, timedelta
import asyncio


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker implementation for external service calls.
    
    Prevents cascading failures by opening the circuit when failure threshold is reached.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery (half-open)
            expected_exception: Exception type that counts as failure
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED
        self.success_count = 0  # For half-open state
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args, **kwargs: Function arguments
        
        Returns:
            Function result
        
        Raises:
            RuntimeError: If circuit is open
            Exception: Original exception from function
        """
        # Check circuit state
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    # Transition to half-open
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    raise RuntimeError(
                        f"Circuit breaker is OPEN. Service unavailable. "
                        f"Retry after {int(self.recovery_timeout - elapsed)} seconds."
                    )
            else:
                raise RuntimeError("Circuit breaker is OPEN. Service unavailable.")
        
        # Execute function
        try:
            result = func(*args, **kwargs)
            
            # Success - reset failure count
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= 2:  # Need 2 successes to close
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            else:
                self.failure_count = 0
            
            return result
            
        except self.expected_exception as e:
            # Failure - increment count
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise
    
    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute async function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args, **kwargs: Function arguments
        
        Returns:
            Function result
        
        Raises:
            RuntimeError: If circuit is open
            Exception: Original exception from function
        """
        # Check circuit state
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    # Transition to half-open
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    raise RuntimeError(
                        f"Circuit breaker is OPEN. Service unavailable. "
                        f"Retry after {int(self.recovery_timeout - elapsed)} seconds."
                    )
            else:
                raise RuntimeError("Circuit breaker is OPEN. Service unavailable.")
        
        # Execute function
        try:
            result = await func(*args, **kwargs)
            
            # Success - reset failure count
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= 2:  # Need 2 successes to close
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            else:
                self.failure_count = 0
            
            return result
            
        except self.expected_exception as e:
            # Failure - increment count
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise


# Global circuit breakers for external services
openai_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=Exception,
)

gemini_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=Exception,
)

mcp_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=30,
    expected_exception=Exception,
)



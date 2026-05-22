"""Data retention exception registry and governance validation."""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from collections import defaultdict


class GovernanceValidationError(Exception):
    """Raised when governance validation fails."""
    pass


@dataclass
class RetentionException:
    """
    Represents a data retention exception with governance metadata.
    
    Required fields:
    - owner: The accountable owner for this exception
    - reason: Justification for the exception
    - expiration: When the exception expires
    - review_date: When the exception should be reviewed
    """
    id: str
    owner: str
    reason: str
    expiration: date
    review_date: date
    dataset: Optional[str] = None
    artifact_category: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate required fields after initialization."""
        if not self.owner or not self.owner.strip():
            raise GovernanceValidationError("Retention exception requires an owner")
        if not self.reason or not self.reason.strip():
            raise GovernanceValidationError("Retention exception requires a reason")
        if self.expiration is None:
            raise GovernanceValidationError("Retention exception requires an expiration date")
        if self.review_date is None:
            raise GovernanceValidationError("Retention exception requires a review date")
    
    def is_expired(self, as_of: Optional[date] = None) -> bool:
        """Check if the exception has expired."""
        check_date = as_of or date.today()
        return self.expiration < check_date
    
    def is_active(self, as_of: Optional[date] = None) -> bool:
        """Check if the exception is currently active (not expired)."""
        return not self.is_expired(as_of)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary representation."""
        return {
            "id": self.id,
            "owner": self.owner,
            "reason": self.reason,
            "expiration": self.expiration.isoformat(),
            "review_date": self.review_date.isoformat(),
            "dataset": self.dataset,
            "artifact_category": self.artifact_category,
            "created_at": self.created_at.isoformat(),
            "is_expired": self.is_expired(),
        }


class RetentionExceptionRegistry:
    """Registry for managing retention exceptions."""
    
    def __init__(self):
        self._exceptions: Dict[str, RetentionException] = {}
    
    def register(self, exception: RetentionException) -> str:
        """
        Register a new retention exception.
        
        Raises:
            GovernanceValidationError: If validation fails (e.g., missing owner)
        """
        # Validation happens in RetentionException.__post_init__
        if exception.id in self._exceptions:
            raise GovernanceValidationError(f"Exception with id '{exception.id}' already exists")
        
        self._exceptions[exception.id] = exception
        return exception.id
    
    def get(self, exception_id: str) -> Optional[RetentionException]:
        """Get an exception by ID."""
        return self._exceptions.get(exception_id)
    
    def list_all(self) -> List[RetentionException]:
        """List all registered exceptions."""
        return list(self._exceptions.values())
    
    def list_active(self, as_of: Optional[date] = None) -> List[RetentionException]:
        """List all active (non-expired) exceptions."""
        return [e for e in self._exceptions.values() if e.is_active(as_of)]
    
    def list_expired(self, as_of: Optional[date] = None) -> List[RetentionException]:
        """List all expired exceptions."""
        return [e for e in self._exceptions.values() if e.is_expired(as_of)]
    
    def delete(self, exception_id: str) -> bool:
        """Delete an exception by ID. Returns True if deleted, False if not found."""
        if exception_id in self._exceptions:
            del self._exceptions[exception_id]
            return True
        return False
    
    def validate_all(self, as_of: Optional[date] = None) -> List[Dict[str, Any]]:
        """
        Validate all exceptions and return any violations.
        
        Returns:
            List of validation errors for expired exceptions.
        """
        violations = []
        check_date = as_of or date.today()
        
        for exc in self._exceptions.values():
            if exc.is_expired(check_date):
                violations.append({
                    "exception_id": exc.id,
                    "error": f"Exception expired on {exc.expiration.isoformat()}",
                    "owner": exc.owner,
                })
        
        return violations
    
    def group_by_owner(self, active_only: bool = False, as_of: Optional[date] = None) -> Dict[str, List[RetentionException]]:
        """
        Group exceptions by owner.
        
        Args:
            active_only: If True, only include active exceptions
            as_of: Date to check expiration against
        
        Returns:
            Dictionary mapping owner to list of their exceptions
        """
        grouped = defaultdict(list)
        exceptions = self.list_active(as_of) if active_only else self.list_all()
        
        for exc in exceptions:
            grouped[exc.owner].append(exc)
        
        return dict(grouped)


@dataclass
class RetentionExceptionReport:
    """Report for retention exceptions grouped by owner."""
    
    registry: RetentionExceptionRegistry
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    def generate(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate a report of active exceptions grouped by owner.
        
        Returns:
            Report dictionary with summary and details by owner.
        """
        active_by_owner = self.registry.group_by_owner(active_only=True, as_of=as_of)
        expired = self.registry.list_expired(as_of)
        violations = self.registry.validate_all(as_of)
        
        report = {
            "generated_at": self.generated_at.isoformat(),
            "as_of": (as_of or date.today()).isoformat(),
            "summary": {
                "total_exceptions": len(self.registry.list_all()),
                "active_exceptions": len(self.registry.list_active(as_of)),
                "expired_exceptions": len(expired),
                "unique_owners": len(active_by_owner),
                "validation_violations": len(violations),
            },
            "active_by_owner": {
                owner: [exc.to_dict() for exc in exceptions]
                for owner, exceptions in active_by_owner.items()
            },
            "expired_exceptions": [exc.to_dict() for exc in expired],
            "violations": violations,
        }
        
        return report
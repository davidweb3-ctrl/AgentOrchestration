"""Authentication and authorization service for API key settings."""

import time
from enum import Enum
from typing import Dict, Optional, Set
from dataclasses import dataclass, field


class PrincipalStatus(Enum):
    """Principal authentication status."""
    VALID = "valid"
    STALE = "stale"
    REVOKED = "revoked"
    EXPIRED = "expired"
    ANONYMOUS = "anonymous"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    INSUFFICIENT_ROLE = "insufficient_role"
    WRONG_WORKSPACE = "wrong_workspace"


class WorkspaceRole(Enum):
    """Workspace roles for authorization."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass
class Principal:
    """Authenticated principal representation."""
    id: str
    workspace_id: str
    role: WorkspaceRole
    scopes: Set[str] = field(default_factory=set)
    mfa_verified_at: Optional[float] = None
    session_created_at: float = field(default_factory=time.time)
    status: PrincipalStatus = PrincipalStatus.VALID
    
    def is_fresh(self, max_age_seconds: int = 3600) -> bool:
        """Check if principal session is fresh (not stale)."""
        if self.status in (PrincipalStatus.STALE, PrincipalStatus.EXPIRED):
            return False
        session_age = time.time() - self.session_created_at
        return session_age < max_age_seconds
    
    def has_mfa_challenge(self, max_age_seconds: int = 300) -> bool:
        """Check if principal has recent MFA verification."""
        if self.mfa_verified_at is None:
            return False
        mfa_age = time.time() - self.mfa_verified_at
        return mfa_age < max_age_seconds


class AuthService:
    """Central authentication and authorization service."""
    
    # Required scope for privileged API key operations
    PRIVILEGED_KEY_SCOPE = "api_keys:create"
    
    # Roles allowed to create privileged keys
    PRIVILEGED_ROLES = {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}
    
    # MFA challenge max age in seconds (5 minutes)
    MFA_MAX_AGE = 300
    
    # Session max age in seconds (1 hour)
    SESSION_MAX_AGE = 3600
    
    def __init__(self):
        self._revoked_tokens: Set[str] = set()
        self._disabled_principals: Set[str] = set()
    
    def revoke_token(self, token: str) -> None:
        """Mark a token as revoked."""
        self._revoked_tokens.add(token)
    
    def disable_principal(self, principal_id: str) -> None:
        """Disable a principal."""
        self._disabled_principals.add(principal_id)
    
    def validate_principal(
        self,
        principal: Optional[Principal],
        required_workspace_id: Optional[str] = None
    ) -> PrincipalStatus:
        """
        Validate a principal for privileged operations.
        
        Returns the validation status of the principal.
        """
        if principal is None:
            return PrincipalStatus.ANONYMOUS
        
        if principal.id in self._disabled_principals:
            return PrincipalStatus.REVOKED
        
        if principal.status == PrincipalStatus.REVOKED:
            return PrincipalStatus.REVOKED
        
        if not principal.is_fresh(self.SESSION_MAX_AGE):
            return PrincipalStatus.STALE
        
        if required_workspace_id and principal.workspace_id != required_workspace_id:
            return PrincipalStatus.WRONG_WORKSPACE
        
        if self.PRIVILEGED_KEY_SCOPE not in principal.scopes:
            return PrincipalStatus.INSUFFICIENT_SCOPE
        
        if principal.role not in self.PRIVILEGED_ROLES:
            return PrincipalStatus.INSUFFICIENT_ROLE
        
        return PrincipalStatus.VALID
    
    def require_mfa_for_privileged_key(
        self,
        principal: Principal,
        required_workspace_id: Optional[str] = None
    ) -> Dict:
        """
        Require MFA challenge for privileged API key creation.
        
        Args:
            principal: The authenticated principal
            required_workspace_id: Optional workspace ID to validate against
            
        Returns:
            Dict with 'allowed' boolean and 'reason' string
        """
        # First validate the principal
        status = self.validate_principal(principal, required_workspace_id)
        
        if status == PrincipalStatus.ANONYMOUS:
            return {"allowed": False, "reason": "Anonymous principals denied"}
        
        if status == PrincipalStatus.REVOKED:
            return {"allowed": False, "reason": "Revoked principal"}
        
        if status == PrincipalStatus.STALE:
            return {"allowed": False, "reason": "Stale credentials"}
        
        if status == PrincipalStatus.WRONG_WORKSPACE:
            return {"allowed": False, "reason": "Wrong workspace"}
        
        if status == PrincipalStatus.INSUFFICIENT_SCOPE:
            return {"allowed": False, "reason": "Insufficient scope"}
        
        if status == PrincipalStatus.INSUFFICIENT_ROLE:
            return {"allowed": False, "reason": "Insufficient role"}
        
        # Check MFA challenge
        if not principal.has_mfa_challenge(self.MFA_MAX_AGE):
            return {"allowed": False, "reason": "MFA challenge required"}
        
        return {"allowed": True, "reason": "Authorized"}
    
    def verify_mfa_challenge(self, principal: Principal) -> Principal:
        """Mark principal as having completed MFA challenge."""
        principal.mfa_verified_at = time.time()
        return principal

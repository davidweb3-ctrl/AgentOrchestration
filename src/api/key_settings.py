"""API key settings endpoints with MFA challenge requirement."""

from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional

from .auth_service import AuthService, Principal, PrincipalStatus, WorkspaceRole

router = APIRouter()
auth_service = AuthService()


def get_principal_from_token(authorization: Optional[str] = Header(None)) -> Optional[Principal]:
    """
    Extract and validate principal from Authorization header.
    
    This is a simplified implementation. In production, this would:
    - Validate JWT tokens
    - Check token signatures
    - Query user database
    - Handle session cookies for browser clients
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    # Check if token is revoked
    if token in auth_service._revoked_tokens:
        return None
    
    # In production, decode token and fetch user details
    # For this implementation, we parse mock token format: "user_id:workspace_id:role:scopes:mfa_timestamp"
    try:
        parts = token.split(":")
        if len(parts) >= 4:
            user_id = parts[0]
            workspace_id = parts[1]
            role = WorkspaceRole(parts[2])
            scopes = set(parts[3].split(","))
            
            # Optional MFA timestamp
            mfa_verified_at = None
            if len(parts) >= 5 and parts[4]:
                import time
                mfa_verified_at = float(parts[4])
            
            return Principal(
                id=user_id,
                workspace_id=workspace_id,
                role=role,
                scopes=scopes,
                mfa_verified_at=mfa_verified_at
            )
    except (ValueError, IndexError):
        pass
    
    return None


@router.post("/keys/privileged")
async def create_privileged_api_key(
    name: str,
    key_type: str = "service_account",
    principal: Optional[Principal] = Depends(get_principal_from_token),
    x_workspace_id: Optional[str] = Header(None)
):
    """
    Create a privileged API key.
    
    Requires:
    - Valid authentication (not stale, revoked, or anonymous)
    - MFA challenge completed within last 5 minutes
    - api_keys:create scope
    - Owner or Admin role
    - Correct workspace
    """
    # Determine required workspace
    required_workspace = x_workspace_id
    if principal and not required_workspace:
        required_workspace = principal.workspace_id
    
    # Check authorization with MFA requirement
    result = auth_service.require_mfa_for_privileged_key(principal, required_workspace)
    
    if not result["allowed"]:
        raise HTTPException(status_code=403, detail=result["reason"])
    
    # In production, actually create the API key
    return {
        "status": "created",
        "key_name": name,
        "key_type": key_type,
        "workspace_id": required_workspace,
        "created_by": principal.id if principal else None
    }


@router.post("/auth/mfa/verify")
async def verify_mfa(
    code: str,
    principal: Optional[Principal] = Depends(get_principal_from_token)
):
    """
    Verify MFA code and update principal's MFA status.
    
    In production, this would validate TOTP/SMS codes.
    """
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # In production, validate MFA code against stored secret
    # For this implementation, we accept any 6-digit code
    if not code or len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Invalid MFA code format")
    
    # Mark MFA as verified
    auth_service.verify_mfa_challenge(principal)
    
    return {
        "status": "verified",
        "user_id": principal.id,
        "mfa_verified_at": principal.mfa_verified_at
    }


@router.get("/auth/status")
async def check_auth_status(
    principal: Optional[Principal] = Depends(get_principal_from_token)
):
    """Check current authentication status."""
    if principal is None:
        return {"authenticated": False, "status": "anonymous"}
    
    validation = auth_service.validate_principal(principal)
    
    return {
        "authenticated": True,
        "user_id": principal.id,
        "workspace_id": principal.workspace_id,
        "role": principal.role.value,
        "scopes": list(principal.scopes),
        "status": validation.value,
        "mfa_verified": principal.has_mfa_challenge(),
        "session_fresh": principal.is_fresh()
    }

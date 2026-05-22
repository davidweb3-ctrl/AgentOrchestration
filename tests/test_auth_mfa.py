"""Tests for authentication and MFA challenge on privileged key creation."""

import time
import pytest
from src.api.auth_service import (
    AuthService,
    Principal,
    PrincipalStatus,
    WorkspaceRole,
)


class TestAuthService:
    """Test the central authentication service."""

    def setup_method(self):
        self.auth_service = AuthService()
        self.valid_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create", "agents:read"},
            mfa_verified_at=time.time(),
        )

    def test_valid_principal_allowed(self):
        """Authorized users with correct role and MFA can create privileged keys."""
        result = self.auth_service.require_mfa_for_privileged_key(
            self.valid_principal, "ws-456"
        )
        assert result["allowed"] is True
        assert result["reason"] == "Authorized"

    def test_anonymous_principal_denied(self):
        """Anonymous principals are denied."""
        result = self.auth_service.require_mfa_for_privileged_key(None, "ws-456")
        assert result["allowed"] is False
        assert "Anonymous" in result["reason"]

    def test_revoked_principal_denied(self):
        """Revoked principals are denied."""
        self.auth_service.revoke_token("token-123")
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
        )
        # Simulate revoked status
        principal.status = PrincipalStatus.REVOKED
        result = self.auth_service.require_mfa_for_privileged_key(principal, "ws-456")
        assert result["allowed"] is False
        assert "Revoked" in result["reason"]

    def test_disabled_principal_denied(self):
        """Disabled principals are denied."""
        self.auth_service.disable_principal("user-123")
        result = self.auth_service.require_mfa_for_privileged_key(
            self.valid_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "Revoked" in result["reason"]

    def test_stale_session_denied(self):
        """Stale credentials are denied."""
        stale_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
            session_created_at=time.time() - 7200,  # 2 hours ago
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            stale_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "Stale" in result["reason"]

    def test_wrong_workspace_denied(self):
        """Principals from wrong workspace are denied."""
        result = self.auth_service.require_mfa_for_privileged_key(
            self.valid_principal, "ws-different"
        )
        assert result["allowed"] is False
        assert "workspace" in result["reason"].lower()

    def test_insufficient_scope_denied(self):
        """Principals without api_keys:create scope are denied."""
        no_scope_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"agents:read"},  # Missing api_keys:create
            mfa_verified_at=time.time(),
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            no_scope_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "scope" in result["reason"].lower()

    def test_insufficient_role_denied(self):
        """Non-admin/owner roles are denied."""
        member_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.MEMBER,  # Not admin or owner
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            member_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "role" in result["reason"].lower()

    def test_viewer_role_denied(self):
        """Viewer role is denied."""
        viewer_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.VIEWER,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            viewer_principal, "ws-456"
        )
        assert result["allowed"] is False

    def test_missing_mfa_denied(self):
        """Principals without MFA verification are denied."""
        no_mfa_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=None,
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            no_mfa_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "MFA" in result["reason"]

    def test_stale_mfa_denied(self):
        """Stale MFA (older than 5 minutes) is denied."""
        stale_mfa_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time() - 600,  # 10 minutes ago
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            stale_mfa_principal, "ws-456"
        )
        assert result["allowed"] is False
        assert "MFA" in result["reason"]

    def test_owner_role_allowed(self):
        """Owner role can create privileged keys."""
        owner_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.OWNER,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
        )
        result = self.auth_service.require_mfa_for_privileged_key(
            owner_principal, "ws-456"
        )
        assert result["allowed"] is True

    def test_mfa_verification_updates_timestamp(self):
        """MFA verification updates the principal's MFA timestamp."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=None,
        )
        
        # Initially no MFA
        assert principal.mfa_verified_at is None
        
        # Verify MFA
        self.auth_service.verify_mfa_challenge(principal)
        
        # Now has fresh MFA
        assert principal.mfa_verified_at is not None
        assert principal.has_mfa_challenge()


class TestPrincipalValidation:
    """Test principal validation logic."""

    def setup_method(self):
        self.auth_service = AuthService()

    def test_validate_anonymous(self):
        """Anonymous principal validation returns correct status."""
        status = self.auth_service.validate_principal(None)
        assert status == PrincipalStatus.ANONYMOUS

    def test_validate_valid_principal(self):
        """Valid principal passes validation."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
        )
        status = self.auth_service.validate_principal(principal, "ws-456")
        assert status == PrincipalStatus.VALID

    def test_principal_freshness_check(self):
        """Principal freshness is correctly determined."""
        fresh_principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            session_created_at=time.time() - 1800,  # 30 minutes ago
        )
        assert fresh_principal.is_fresh(max_age_seconds=3600) is True
        assert fresh_principal.is_fresh(max_age_seconds=900) is False

    def test_mfa_freshness_check(self):
        """MFA freshness is correctly determined."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            mfa_verified_at=time.time() - 180,  # 3 minutes ago
        )
        assert principal.has_mfa_challenge(max_age_seconds=300) is True
        assert principal.has_mfa_challenge(max_age_seconds=120) is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def setup_method(self):
        self.auth_service = AuthService()

    def test_empty_scopes_denied(self):
        """Principal with empty scopes is denied."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes=set(),
            mfa_verified_at=time.time(),
        )
        result = self.auth_service.require_mfa_for_privileged_key(principal, "ws-456")
        assert result["allowed"] is False

    def test_malformed_token_handled(self):
        """Malformed tokens are handled gracefully."""
        # This would be handled by get_principal_from_token in practice
        # Here we test the service layer handles None correctly
        result = self.auth_service.require_mfa_for_privileged_key(None)
        assert result["allowed"] is False

    def test_expired_session_edge_case(self):
        """Exactly at session max age boundary."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time(),
            session_created_at=time.time() - 3600,  # Exactly at boundary
        )
        # Should be considered stale at exact boundary
        assert principal.is_fresh(max_age_seconds=3600) is False

    def test_mfa_boundary(self):
        """Exactly at MFA max age boundary."""
        principal = Principal(
            id="user-123",
            workspace_id="ws-456",
            role=WorkspaceRole.ADMIN,
            scopes={"api_keys:create"},
            mfa_verified_at=time.time() - 300,  # Exactly at boundary
        )
        # Should require fresh MFA at exact boundary
        assert principal.has_mfa_challenge(max_age_seconds=300) is False

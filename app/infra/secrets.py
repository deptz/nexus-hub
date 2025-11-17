"""Secrets management with Vault and AWS Secrets Manager support."""

import os
from typing import Optional

# Try to import vault clients
try:
    import hvac
    HAS_VAULT = True
except ImportError:
    HAS_VAULT = False

try:
    import boto3
    HAS_AWS = True
except ImportError:
    HAS_AWS = False


class SecretsManager:
    """Unified secrets manager supporting multiple backends."""
    
    def __init__(self):
        self.vault_client = None
        self.aws_client = None
        self._init_vault()
        self._init_aws()
    
    def _init_vault(self):
        """Initialize HashiCorp Vault client if configured."""
        if not HAS_VAULT:
            return
        
        vault_url = os.getenv("VAULT_ADDR")
        vault_token = os.getenv("VAULT_TOKEN")
        
        if vault_url and vault_token:
            try:
                self.vault_client = hvac.Client(url=vault_url, token=vault_token)
                # Test connection
                self.vault_client.is_authenticated()
            except Exception:
                self.vault_client = None
    
    def _init_aws(self):
        """Initialize AWS Secrets Manager client if configured."""
        if not HAS_AWS:
            return
        
        aws_region = os.getenv("AWS_REGION")
        if aws_region:
            try:
                self.aws_client = boto3.client("secretsmanager", region_name=aws_region)
            except Exception:
                self.aws_client = None
    
    def get_secret(self, secret_ref: str) -> Optional[str]:
        """
        Get secret from vault reference or environment variable.
        
        Supports:
        - vault://secret/path/key - HashiCorp Vault
        - aws://secret-name/key - AWS Secrets Manager
        - env://VAR_NAME - Environment variable
        - Direct value (if not a reference)
        
        Args:
            secret_ref: Secret reference or direct value
        
        Returns:
            Secret value or None if not found
        """
        if not secret_ref:
            return None
        
        # Direct value (not a reference)
        if not secret_ref.startswith(("vault://", "aws://", "env://")):
            return secret_ref
        
        # Vault reference: vault://secret/path/key
        if secret_ref.startswith("vault://"):
            return self._get_vault_secret(secret_ref)
        
        # AWS Secrets Manager: aws://secret-name/key
        if secret_ref.startswith("aws://"):
            return self._get_aws_secret(secret_ref)
        
        # Environment variable: env://VAR_NAME
        if secret_ref.startswith("env://"):
            var_name = secret_ref[6:]
            return os.getenv(var_name)
        
        return None
    
    def _get_vault_secret(self, vault_ref: str) -> Optional[str]:
        """Get secret from HashiCorp Vault."""
        if not self.vault_client:
            return None
        
        try:
            # Parse vault://secret/path/key
            path = vault_ref[8:]  # Remove "vault://"
            parts = path.split("/")
            
            if len(parts) < 2:
                return None
            
            secret_path = "/".join(parts[:-1])
            key = parts[-1]
            
            # Read secret
            response = self.vault_client.secrets.kv.v2.read_secret_version(path=secret_path)
            data = response.get("data", {}).get("data", {})
            return data.get(key)
        except Exception:
            return None
    
    def _get_aws_secret(self, aws_ref: str) -> Optional[str]:
        """Get secret from AWS Secrets Manager."""
        if not self.aws_client:
            return None
        
        try:
            # Parse aws://secret-name/key
            path = aws_ref[6:]  # Remove "aws://"
            parts = path.split("/")
            
            if len(parts) < 2:
                return None
            
            secret_name = parts[0]
            key = "/".join(parts[1:])
            
            # Get secret
            response = self.aws_client.get_secret_value(SecretId=secret_name)
            secret_string = response.get("SecretString", "{}")
            
            # Parse as JSON
            import json
            secret_data = json.loads(secret_string)
            return secret_data.get(key)
        except Exception:
            return None


# Global secrets manager instance
secrets_manager = SecretsManager()


def get_secret(secret_ref: str, fallback: Optional[str] = None) -> Optional[str]:
    """
    Convenience function to get a secret.
    
    Args:
        secret_ref: Secret reference (vault://, aws://, env://) or direct value
        fallback: Fallback value if secret not found
    
    Returns:
        Secret value or fallback
    """
    value = secrets_manager.get_secret(secret_ref)
    return value if value is not None else fallback


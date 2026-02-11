-- Migration v12 to v13: Add client certificate password field (reserved for future use)
--
-- Note: Currently only unencrypted client certificates are supported.
-- This field is added for database schema completeness and potential future enhancement.
--
-- Field: client_cert_password TEXT
-- - Reserved for future use (encrypted certs not currently supported)
-- - Would be base64 encoded if used (like other passwords in account table)
-- - NULL (unused)

-- Add client_cert_password column
ALTER TABLE account ADD COLUMN client_cert_password TEXT;

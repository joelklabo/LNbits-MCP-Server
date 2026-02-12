"""Curated descriptions for high-use tools.

Auto-generated OpenAPI summaries are often terse (e.g. "Api Wallet").
These overrides provide LLM-friendly descriptions for common operations.
"""

CURATED_DESCRIPTIONS: dict[str, str] = {
    # Core wallet
    "wallet_get_wallet": (
        "Get wallet details including ID, name, balance (in msats — divide by "
        "1000 for sats), and key status. Do not reveal admin/invoice keys to "
        "the user."
    ),
    "wallet_create_wallet": "Create a new wallet.",
    "wallet_rename_wallet": "Rename an existing wallet.",
    "wallet_delete_wallet": "Delete a wallet by ID.",
    # Payments
    "payments_list_payments": (
        "List recent payments. Each entry includes payment_hash, amount (msats), "
        "memo, and status."
    ),
    "payments_create_payments": (
        "Create an invoice (out=false) or pay a BOLT11 invoice (out=true). "
        "Amount is in sats when unit='sat'. "
        "When creating an invoice, the response includes qr_code (URL to a "
        "scannable QR code image) and lightning_uri — display both to the user. "
        "IMPORTANT: 'out' must be a boolean (not string), 'amount' must be a "
        "number (not string)."
    ),
    "payments_get_payment": "Get the status of a specific payment by its hash.",
    "payments_decode_payment": (
        "Decode a BOLT11 invoice to reveal amount, memo, payee, and expiry."
    ),
    # LNURLp
    "lnurlp_list_links": "List all LNURL-pay links for the current wallet.",
    "lnurlp_create_link": "Create a new LNURL-pay link.",
    "lnurlp_get_link": "Get details of a specific LNURL-pay link.",
    "lnurlp_update_link": "Update an existing LNURL-pay link.",
    "lnurlp_delete_link": "Delete a LNURL-pay link.",
    # Extensions
    "extension_managment_list_extensions": "List all available LNbits extensions.",
    "extension_managment_install_extension": "Install or update an extension.",
}

# Tags that produce HTML pages, not API JSON — skip them
SKIP_TAGS: set[str] = {
    "Admin UI",
    "Webpush",
    "Websocket",
}

# Telegram Adapter Setup Guide

This guide explains how to set up and use the Telegram adapter for testing the orchestrator.

## Overview

The Telegram adapter allows you to test the orchestrator by sending messages through Telegram. It:
- Receives webhook updates from Telegram
- Converts them to `CanonicalMessage` format
- Processes them through the orchestrator
- Sends responses back to Telegram

## Prerequisites

1. A Telegram bot token (get one from [@BotFather](https://t.me/botfather))
2. A tenant ID in your database
3. The orchestrator running and accessible via HTTPS (for webhooks) or using a tunnel like ngrok for local testing

## Setup Steps

### 1. Get a Telegram Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the instructions
3. Copy the bot token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Configure Environment Variables

Add to your `.env` file:

```bash
# Telegram Bot Token
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Optional: Default tenant ID for testing (otherwise pass as query param)
TELEGRAM_DEFAULT_TENANT_ID=your_tenant_uuid_here
```

### 3. Set Up Webhook URL

The Telegram webhook endpoint is: `POST /webhooks/telegram`

For local testing, use a tunnel service like ngrok:

```bash
# Install ngrok if you haven't
# Then expose your local server
ngrok http 8000

# You'll get a URL like: https://abc123.ngrok.io
```

### 4. Register Webhook with Telegram

Use the Telegram Bot API to set your webhook:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain.com/webhooks/telegram?tenant_id=YOUR_TENANT_ID"
  }'
```

Or for local testing with ngrok:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://abc123.ngrok.io/webhooks/telegram?tenant_id=YOUR_TENANT_ID"
  }'
```

**Note:** If you set `TELEGRAM_DEFAULT_TENANT_ID` in your `.env`, you can omit the `tenant_id` query parameter.

### 5. Verify Webhook

Check if webhook is set correctly:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

### 6. Test

1. Start your orchestrator:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Send a message to your bot on Telegram

3. The bot should process the message through the orchestrator and respond

## How It Works

1. **Telegram sends webhook** → `POST /webhooks/telegram` with update object
2. **Adapter converts** → Telegram update → `CanonicalMessage`
3. **Orchestrator processes** → Same flow as `/messages/inbound` endpoint
4. **Adapter sends response** → `CanonicalMessage` → Telegram message

## Message Flow

```
Telegram User
    ↓ (sends message)
Telegram Servers
    ↓ (webhook POST)
/webhooks/telegram endpoint
    ↓ (converts to CanonicalMessage)
handle_inbound_message_sync()
    ↓ (orchestrator processing)
LLM + Tools
    ↓ (generates response)
CanonicalMessage (outbound)
    ↓ (converts back to Telegram)
Telegram Bot API
    ↓ (sends message)
Telegram User
```

## Troubleshooting

### Bot doesn't respond

1. Check webhook is set: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
2. Check server logs for errors
3. Verify `TELEGRAM_BOT_TOKEN` is set correctly
4. Verify tenant_id is valid and exists in database

### Webhook not receiving updates

1. Ensure your server is accessible via HTTPS (or use ngrok)
2. Telegram requires HTTPS for webhooks (except localhost in some cases)
3. Check firewall/network settings

### "tenant_id required" error

- Pass `tenant_id` as query parameter: `/webhooks/telegram?tenant_id=YOUR_UUID`
- Or set `TELEGRAM_DEFAULT_TENANT_ID` in `.env`

### Rate limiting

Telegram has rate limits. If you hit them:
- Wait a few seconds between messages
- Check Telegram's rate limit documentation

## Advanced: Multiple Tenants

To support multiple tenants, you can:
1. Use different bots (one per tenant)
2. Route based on chat_id or user_id in metadata
3. Use a mapping table in your database

For now, the adapter uses a single tenant_id per webhook endpoint.

## Security Notes

- **Never commit** your `TELEGRAM_BOT_TOKEN` to version control
- Use environment variables or secrets management
- Consider adding webhook secret verification (not implemented yet)
- Validate tenant_id to prevent unauthorized access

## Example Webhook Payload

Telegram sends updates like this:

```json
{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": {
      "id": 987654321,
      "is_bot": false,
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe"
    },
    "chat": {
      "id": 987654321,
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe",
      "type": "private"
    },
    "date": 1234567890,
    "text": "Hello, bot!"
  }
}
```

This gets converted to a `CanonicalMessage` with:
- `channel`: "telegram"
- `direction`: "inbound"
- `from.external_id`: "987654321"
- `content.text`: "Hello, bot!"
- `metadata.telegram_chat_id`: "987654321"


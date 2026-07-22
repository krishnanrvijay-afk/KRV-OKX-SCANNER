# KRV-BYBIT-SCANNER

**Status: Pending deployment**

Part of the KRV Scanner System.

## Architecture
- **Mode**: Dual-mode (bounce mean-reversion + trend continuation)
- **Regime**: Venue-specific, computed from Bybit BTC feed
- **Settings**: Read from Supabase `venue_settings` (venue = 'Bybit')
- **Reports to**: [KRV-SCANNER-COMMAND-CENTER](https://github.com/krishnanrvijay-afk/KRV-SCANNER-COMMAND-CENTER)

## System Map
| Repo | Role |
|------|------|
| KRV-SCANNER-COMMAND-CENTER | Brain — command center, settings UI, regime display |
| KRV-HL-SCANNER | Brawn — HL execution, HL regime |
| KRV-MEXC-SCANNER | Brawn — MEXC execution, MEXC regime |
| KRV-BYBIT-SCANNER | Brawn — Bybit execution, Bybit regime (this repo) |

## Baseline
- `v0.0-scaffold` — Repository created, pending scanner build

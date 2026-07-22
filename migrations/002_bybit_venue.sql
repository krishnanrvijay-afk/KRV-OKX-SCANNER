-- 002_bybit_venue.sql
-- Run this in Supabase SQL editor to add Bybit trade log + scanner state tables

CREATE TABLE IF NOT EXISTS bybit_trade_log (
    id              bigserial PRIMARY KEY,
    created_at      timestamptz DEFAULT now(),
    symbol          text,
    direction       text,
    exchange        text DEFAULT 'BYBIT',
    entry_price     float,
    exit_price      float,
    sl_price        float,
    tp1_price       float,
    size            float,
    pnl             float,
    r               float,
    reason          text,
    session         text,
    paper           boolean DEFAULT true,
    trade_mode      text DEFAULT 'BOUNCE',
    regime          text,
    j15m_entry      float,
    j1h_entry       float,
    stoch_k_entry   float,
    stoch_d_entry   float,
    rsi_entry       float,
    depth_pct_entry float,
    chg24h_entry    float,
    session_opened  text,
    mae_r           float,
    mfe_r           float,
    score           integer,
    adx1h           float
);

CREATE TABLE IF NOT EXISTS bybit_scanner_state (
    id          integer PRIMARY KEY DEFAULT 1,
    halt_long   boolean DEFAULT false,
    halt_short  boolean DEFAULT false,
    updated_at  timestamptz DEFAULT now()
);

INSERT INTO bybit_scanner_state (id, halt_long, halt_short)
VALUES (1, false, false)
ON CONFLICT (id) DO NOTHING;

-- Ensure BYBIT row exists in venue_live_state
INSERT INTO venue_live_state (venue, regime, confidence, btc_j1h, momentum_5c, updated_at)
VALUES ('BYBIT', 'RANGING', 'HIGH', 50.0, 0.0, now())
ON CONFLICT (venue) DO NOTHING;

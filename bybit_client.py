import asyncio
import base64
import hashlib
import hmac
import json
import time
import logging
from typing import Optional
import os
import httpx

log = logging.getLogger("okx_client")

OKX_BASE = "https://www.okx.com"

_TF_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}

def _sym(symbol: str) -> str:
    """Internal symbol (BTC) -> OKX format (BTC-USDT-SWAP)."""
    if "-" in symbol:
        return symbol
    return f"{symbol}-USDT-SWAP"

def _tf(interval: str) -> str:
    return _TF_MAP.get(interval, interval)


class OkxClient:
    def __init__(self):
        self.api_key        = os.environ.get("OKX_API_KEY", "")
        self.api_secret     = os.environ.get("OKX_API_SECRET", "")
        self.api_passphrase = os.environ.get("OKX_PASSPHRASE", "")
        self._http: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=OKX_BASE, timeout=10.0)
        return self._http

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        ts = str(time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))
        msg = ts + method.upper() + path + body
        sig = base64.b64encode(
            hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY":        self.api_key,
            "OK-ACCESS-SIGN":       sig,
            "OK-ACCESS-TIMESTAMP":  ts,
            "OK-ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type":         "application/json",
        }

    # ── Public endpoints ──────────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> Optional[float]:
        try:
            r = await self._client().get("/api/v5/market/ticker",
                params={"instId": _sym(symbol)})
            data = r.json().get("data", [])
            return float(data[0]["last"]) if data else None
        except Exception as e:
            log.warning(f"get_price {symbol}: {e}")
        return None

    async def get_all_prices(self) -> dict[str, float]:
        try:
            r = await self._client().get("/api/v5/market/tickers",
                params={"instType": "SWAP"})
            out = {}
            for item in r.json().get("data", []):
                inst = item.get("instId", "")
                if inst.endswith("-USDT-SWAP"):
                    coin = inst.replace("-USDT-SWAP", "")
                    out[coin] = float(item["last"])
            return out
        except Exception as e:
            log.warning(f"get_all_prices: {e}")
        return {}

    async def get_all_price_changes(self, symbols: list[str]) -> dict[str, float]:
        try:
            r = await self._client().get("/api/v5/market/tickers",
                params={"instType": "SWAP"})
            sym_set = {f"{s}-USDT-SWAP" for s in symbols}
            out = {}
            for item in r.json().get("data", []):
                inst = item.get("instId", "")
                if inst in sym_set:
                    last  = float(item.get("last",    0) or 0)
                    open_ = float(item.get("open24h", last) or last)
                    if open_ > 0:
                        coin = inst.replace("-USDT-SWAP", "")
                        out[coin] = round((last - open_) / open_ * 100, 2)
            return out
        except Exception as e:
            log.warning(f"get_all_price_changes: {e}")
        return {}

    async def get_candles(self, symbol: str, interval: str, limit: int = 50) -> list[dict]:
        try:
            r = await self._client().get("/api/v5/market/candles", params={
                "instId": _sym(symbol),
                "bar":    _tf(interval),
                "limit":  limit,
            })
            raw = r.json().get("data", [])
            # OKX returns [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm], newest first
            candles = []
            for row in reversed(raw):
                candles.append({
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": float(row[5]),
                    "time":   int(row[0]),
                })
            return candles
        except Exception as e:
            log.warning(f"get_candles {symbol} {interval}: {e}")
        return []

    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        try:
            r = await self._client().get("/api/v5/market/books", params={
                "instId": _sym(symbol),
                "sz":     depth,
            })
            res = r.json().get("data", [{}])[0]
            bid_vol = sum(float(b[1]) for b in res.get("bids", []))
            ask_vol = sum(float(a[1]) for a in res.get("asks", []))
            total = bid_vol + ask_vol
            if total == 0:
                return {"bid_pct": 50.0, "ask_pct": 50.0, "total_vol": 0}
            return {
                "bid_pct":   round(bid_vol / total * 100, 1),
                "ask_pct":   round(ask_vol / total * 100, 1),
                "total_vol": total,
            }
        except Exception as e:
            log.warning(f"get_orderbook {symbol}: {e}")
        return {"bid_pct": 50.0, "ask_pct": 50.0, "total_vol": 0}

    async def get_funding_rate(self, symbol: str) -> Optional[float]:
        try:
            r = await self._client().get("/api/v5/public/funding-rate",
                params={"instId": _sym(symbol)})
            data = r.json().get("data", [])
            return float(data[0].get("fundingRate", 0)) if data else None
        except Exception as e:
            log.warning(f"get_funding_rate {symbol}: {e}")
        return None

    # ── Private endpoints ─────────────────────────────────────────────────────

    async def get_open_position_size(self, symbol: str):
        try:
            path = f"/api/v5/account/positions?instId={_sym(symbol)}"
            r = await self._client().get(path,
                headers=self._sign("GET", path))
            for pos in r.json().get("data", []):
                sz = float(pos.get("pos", 0))
                if sz > 0:
                    return sz
        except Exception as e:
            log.warning(f"get_open_position_size {symbol}: {e}")
        return 0.0

    async def open_position(
        self,
        symbol: str,
        direction: str,
        size: float,
        sl_price: float,
        tp_price: Optional[float] = None,
        leverage: int = 5,
    ) -> dict:
        try:
            path = "/api/v5/trade/order"
            body: dict = {
                "instId":    _sym(symbol),
                "tdMode":    "cross",
                "side":      "buy" if direction == "LONG" else "sell",
                "ordType":   "market",
                "sz":        str(size),
                "slTriggerPx": str(round(sl_price, 6)),
                "slOrdPx":     "-1",
            }
            if tp_price:
                body["tpTriggerPx"] = str(round(tp_price, 6))
                body["tpOrdPx"]     = "-1"
            body_str = json.dumps(body)
            r = await self._client().post(path, content=body_str,
                headers=self._sign("POST", path, body_str))
            return r.json()
        except Exception as e:
            log.warning(f"open_position {symbol} {direction}: {e}")
            return {"error": str(e)}

    async def close_position(self, symbol: str, direction: str, size: float) -> dict:
        try:
            path = "/api/v5/trade/order"
            body_str = json.dumps({
                "instId":  _sym(symbol),
                "tdMode":  "cross",
                "side":    "sell" if direction == "LONG" else "buy",
                "ordType": "market",
                "sz":      str(size),
                "reduceOnly": "true",
            })
            r = await self._client().post(path, content=body_str,
                headers=self._sign("POST", path, body_str))
            return r.json()
        except Exception as e:
            log.warning(f"close_position {symbol} {direction}: {e}")
            return {"error": str(e)}

    async def cancel_order(self, coin: str, order_id: str) -> dict:
        try:
            path = "/api/v5/trade/cancel-order"
            body_str = json.dumps({"instId": _sym(coin), "ordId": order_id})
            r = await self._client().post(path, content=body_str,
                headers=self._sign("POST", path, body_str))
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

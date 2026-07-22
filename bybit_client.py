import asyncio
import hashlib
import hmac
import json
import time
import logging
from typing import Optional
import os
import httpx

log = logging.getLogger("bybit_client")

BYBIT_BASE = "https://api.bybit.com"

_TF_MAP = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

def _sym(symbol: str) -> str:
    """Internal symbol (BTC) -> Bybit format (BTCUSDT)."""
    return symbol if symbol.endswith("USDT") else symbol + "USDT"

def _tf(interval: str) -> str:
    return _TF_MAP.get(interval, interval)


class BybitClient:
    def __init__(self):
        self.api_key    = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = os.environ.get("BYBIT_API_SECRET", "")
        self._http: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=BYBIT_BASE, timeout=10.0)
        return self._http

    def _sign(self, timestamp: int, body_str: str) -> dict:
        recv = "5000"
        msg = f"{timestamp}{self.api_key}{recv}{body_str}"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "X-BAPI-API-KEY":      self.api_key,
            "X-BAPI-SIGN":         sig,
            "X-BAPI-TIMESTAMP":    str(timestamp),
            "X-BAPI-RECV-WINDOW":  recv,
        }

    # ── Public endpoints ──────────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> Optional[float]:
        try:
            r = await self._client().get("/v5/market/tickers",
                params={"category": "linear", "symbol": _sym(symbol)})
            lst = r.json().get("result", {}).get("list", [])
            return float(lst[0]["lastPrice"]) if lst else None
        except Exception as e:
            log.warning(f"get_price {symbol}: {e}")
        return None

    async def get_all_prices(self) -> dict[str, float]:
        try:
            r = await self._client().get("/v5/market/tickers", params={"category": "linear"})
            out = {}
            for item in r.json().get("result", {}).get("list", []):
                s = item.get("symbol", "")
                if s.endswith("USDT"):
                    out[s[:-4]] = float(item["lastPrice"])
            return out
        except Exception as e:
            log.warning(f"get_all_prices: {e}")
        return {}

    async def get_all_price_changes(self, symbols: list[str]) -> dict[str, float]:
        try:
            r = await self._client().get("/v5/market/tickers", params={"category": "linear"})
            sym_set = {s + "USDT" for s in symbols}
            out = {}
            for item in r.json().get("result", {}).get("list", []):
                s = item.get("symbol", "")
                if s in sym_set:
                    pct = item.get("price24hPcnt")
                    if pct is not None:
                        out[s[:-4]] = round(float(pct) * 100, 2)
            return out
        except Exception as e:
            log.warning(f"get_all_price_changes: {e}")
        return {}

    async def get_candles(self, symbol: str, interval: str, limit: int = 50) -> list[dict]:
        try:
            r = await self._client().get("/v5/market/kline", params={
                "category": "linear",
                "symbol":   _sym(symbol),
                "interval": _tf(interval),
                "limit":    limit,
            })
            raw = r.json().get("result", {}).get("list", [])
            # Bybit returns [startTime, open, high, low, close, volume, turnover], newest first
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
            r = await self._client().get("/v5/market/orderbook", params={
                "category": "linear",
                "symbol":   _sym(symbol),
                "limit":    depth,
            })
            res = r.json().get("result", {})
            bid_vol = sum(float(b[1]) for b in res.get("b", []))
            ask_vol = sum(float(a[1]) for a in res.get("a", []))
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
            r = await self._client().get("/v5/market/funding/history", params={
                "category": "linear", "symbol": _sym(symbol), "limit": 1,
            })
            lst = r.json().get("result", {}).get("list", [])
            return float(lst[0].get("fundingRate", 0)) if lst else None
        except Exception as e:
            log.warning(f"get_funding_rate {symbol}: {e}")
        return None

    # ── Private endpoints ─────────────────────────────────────────────────────

    async def get_open_position_size(self, symbol: str):
        try:
            ts = int(time.time() * 1000)
            params = f"category=linear&symbol={_sym(symbol)}"
            headers = {**self._sign(ts, params), "Content-Type": "application/json"}
            r = await self._client().get("/v5/position/list",
                params={"category": "linear", "symbol": _sym(symbol)},
                headers=headers)
            for pos in r.json().get("result", {}).get("list", []):
                sz = float(pos.get("size", 0))
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
            ts = int(time.time() * 1000)
            body: dict = {
                "category":      "linear",
                "symbol":        _sym(symbol),
                "side":          "Buy" if direction == "LONG" else "Sell",
                "orderType":     "Market",
                "qty":           str(size),
                "stopLoss":      str(round(sl_price, 6)),
                "slTriggerBy":   "LastPrice",
                "timeInForce":   "IOC",
                "reduceOnly":    False,
                "closeOnTrigger": False,
            }
            if tp_price:
                body["takeProfit"] = str(round(tp_price, 6))
                body["tpTriggerBy"] = "LastPrice"
            body_str = json.dumps(body)
            headers = {**self._sign(ts, body_str), "Content-Type": "application/json"}
            r = await self._client().post("/v5/order/create", content=body_str, headers=headers)
            return r.json()
        except Exception as e:
            log.warning(f"open_position {symbol} {direction}: {e}")
            return {"error": str(e)}

    async def close_position(self, symbol: str, direction: str, size: float) -> dict:
        try:
            ts = int(time.time() * 1000)
            body_str = json.dumps({
                "category":      "linear",
                "symbol":        _sym(symbol),
                "side":          "Sell" if direction == "LONG" else "Buy",
                "orderType":     "Market",
                "qty":           str(size),
                "timeInForce":   "IOC",
                "reduceOnly":    True,
                "closeOnTrigger": True,
            })
            headers = {**self._sign(ts, body_str), "Content-Type": "application/json"}
            r = await self._client().post("/v5/order/create", content=body_str, headers=headers)
            return r.json()
        except Exception as e:
            log.warning(f"close_position {symbol} {direction}: {e}")
            return {"error": str(e)}

    async def cancel_order(self, coin: str, order_id: str) -> dict:
        try:
            ts = int(time.time() * 1000)
            body_str = json.dumps({
                "category": "linear",
                "symbol":   _sym(coin),
                "orderId":  order_id,
            })
            headers = {**self._sign(ts, body_str), "Content-Type": "application/json"}
            r = await self._client().post("/v5/order/cancel", content=body_str, headers=headers)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

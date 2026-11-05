"""
Indicateurs techniques — RSI, MACD, Bollinger, Moyennes Mobiles.
Travaille avec des listes de prix (timestamp, price).
"""
import numpy as np


def sma(prices: list[float], period: int) -> list[float | None]:
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1: i + 1]
        result.append(round(np.mean(window), 2))
    return result


def ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    k = 2 / (period + 1)
    ema_vals = [prices[0]]
    for i in range(1, len(prices)):
        ema_vals.append(round(prices[i] * k + ema_vals[-1] * (1 - k), 2))
    return ema_vals


def rsi(prices: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index (0-100). >70 = suracheté, <30 = survendu."""
    if len(prices) < period + 1:
        return [None] * len(prices)

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    result = [None] * period

    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(round(100 - (100 / (1 + rs)), 2))

    for i in range(period, len(deltas)):
        gain = max(deltas[i], 0)
        loss = abs(min(deltas[i], 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100 - (100 / (1 + rs)), 2))

    return result


def macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD = EMA(12) - EMA(26), Signal = EMA(9) du MACD.
    Retourne macd_line, signal_line, histogram.
    """
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    macd_line = [round(f - s, 2) for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    histogram = [round(m - s, 2) for m, s in zip(macd_line, signal_line)]

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def bollinger_bands(prices: list[float], period: int = 20, std_dev: float = 2.0) -> dict:
    """
    Bandes de Bollinger. Signal si prix sort des bandes.
    """
    middle = sma(prices, period)
    upper = []
    lower = []

    for i in range(len(prices)):
        if middle[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = prices[max(0, i - period + 1): i + 1]
            std = float(np.std(window))
            upper.append(round(middle[i] + std_dev * std, 2))
            lower.append(round(middle[i] - std_dev * std, 2))

    # Signal actuel
    current_price = prices[-1]
    current_upper = upper[-1]
    current_lower = lower[-1]
    signal = "neutral"
    if current_upper and current_price > current_upper:
        signal = "overbought"
    elif current_lower and current_price < current_lower:
        signal = "oversold"

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "signal": signal,
    }


def compute_all_indicators(prices: list[float]) -> dict:
    """Calcule tous les indicateurs d'un coup pour un actif."""
    if len(prices) < 30:
        return {"error": "Not enough data points (need 30+)"}

    rsi_vals = rsi(prices)
    macd_data = macd(prices)
    bb = bollinger_bands(prices)
    sma_20 = sma(prices, 20)
    sma_50 = sma(prices, 50) if len(prices) >= 50 else []

    current_rsi = next((v for v in reversed(rsi_vals) if v is not None), None)

    return {
        "current_price": prices[-1],
        "rsi": {"values": rsi_vals[-30:], "current": current_rsi},
        "macd": {k: v[-30:] for k, v in macd_data.items()},
        "bollinger": {
            "signal": bb["signal"],
            "upper": bb["upper"][-1],
            "middle": bb["middle"][-1],
            "lower": bb["lower"][-1],
        },
        "sma_20": sma_20[-1] if sma_20 else None,
        "sma_50": sma_50[-1] if sma_50 else None,
        "trend": _detect_trend(prices, sma_20, sma_50),
    }


def _detect_trend(prices: list[float], sma20: list, sma50: list) -> str:
    """Détection de tendance simple."""
    if not sma20 or sma20[-1] is None:
        return "unknown"
    if sma50 and sma50[-1] is not None:
        if sma20[-1] > sma50[-1] and prices[-1] > sma20[-1]:
            return "bullish"
        elif sma20[-1] < sma50[-1] and prices[-1] < sma20[-1]:
            return "bearish"
    if prices[-1] > sma20[-1]:
        return "slightly_bullish"
    return "slightly_bearish"

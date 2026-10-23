"""Taux de change EUR/USD partagé par toute l'application (API Frankfurter, données BCE)."""
import json
import threading
import urllib.request

_URL = "https://api.frankfurter.app/latest?from=EUR&to=USD"


class FxRate:
    """Dernier taux EUR→USD chargé ; unique pour toute l'application."""
    rate = None          # 1 EUR = rate USD
    date = ""
    currency = "EUR"     # devise d'affichage et d'export, commune à toute l'application

    @classmethod
    def convert(cls, eur: float, currency: str = "EUR") -> float:
        """Montant en EUR converti vers `currency` (EUR si le taux n'est pas chargé)."""
        if currency == "USD" and cls.rate:
            return eur * cls.rate
        return eur

    @classmethod
    def factor(cls, currency: str = None) -> float:
        currency = currency or cls.currency
        return cls.rate if currency == "USD" and cls.rate else 1.0

    @classmethod
    def symbol(cls, currency: str = None) -> str:
        currency = currency or cls.currency
        return "$" if currency == "USD" and cls.rate else "€"

    @classmethod
    def label(cls) -> str:
        if not cls.rate:
            return "EUR/USD : non chargé"
        return f"1 EUR = {cls.rate:.4f} USD ({cls.date}, BCE)"

    @classmethod
    def fetch_async(cls, on_done):
        """Charge le taux en arrière-plan ; `on_done(ok, message)` est appelé dans le thread GUI."""
        import wx

        def _worker():
            try:
                req = urllib.request.Request(_URL, headers={"User-Agent": "MWQuote/1.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode())
                cls.rate = float(data["rates"]["USD"])
                cls.date = data.get("date", "")
                wx.CallAfter(on_done, True, cls.label())
            except Exception as exc:
                wx.CallAfter(on_done, False, f"EUR/USD : erreur — {str(exc)[:60]}")

        threading.Thread(target=_worker, daemon=True).start()

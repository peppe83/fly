"""Rigenera app/data/iata.json (nomi di città, aeroporti e paesi, in italiano).

Fonte: dati statici pubblici di Travelpayouts. Si lancia a mano quando serve
aggiornare l'elenco (raramente):
    python strumenti/genera_iata.py
"""
import json
import pathlib
import urllib.request

BASE = "https://api.travelpayouts.com/data/it/"
OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "data" / "iata.json"


def scarica(nome: str) -> list[dict]:
    with urllib.request.urlopen(BASE + nome + ".json", timeout=60) as r:
        return json.load(r)


def main() -> None:
    paesi = {p["code"]: p["name"] for p in scarica("countries") if p.get("name")}
    citta = {c["code"]: [c["name"], c.get("country_code") or ""]
             for c in scarica("cities") if c.get("name")}
    # solo aeroporti con voli di linea; [nome aeroporto, codice città, paese]
    aeroporti = {a["code"]: [a["name"], a.get("city_code") or "", a.get("country_code") or ""]
                 for a in scarica("airports") if a.get("flightable") and a.get("name")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"k": paesi, "c": citta, "a": aeroporti},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"scritto {OUT}: {len(paesi)} paesi, {len(citta)} città, {len(aeroporti)} aeroporti")


if __name__ == "__main__":
    main()

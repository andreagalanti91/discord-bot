"""CLI: python -m chento <comando>

  login     login con il tuo account Discord nel browser (sul tuo PC), salva il token in .env
  logout    rimuove il token salvato
  sync      scarica lo storico del canale Discord (account o bot)
  import    importa un export JSON di DiscordChatExporter (fatto col tuo account, in locale)
  analyze   estrae i segnali, esegue backtest replica + Chento+, genera la dashboard
  watch     monitora il canale e invia un alert per ogni nuovo messaggio di Chento
  demo      crea un dataset DEMO sintetico (prezzi reali) per provare tutto senza Discord
  serve     avvia la dashboard su http://localhost:8000/dashboard/
"""
from __future__ import annotations

import argparse
import functools
import http.server
import time

from .config import CONFIG, ROOT
from .db import Store


def cmd_login(a):
    from .login import login
    login()


def cmd_logout(a):
    from .login import logout
    logout()


def cmd_sync(a):
    from .discord_fetch import sync_history
    n = sync_history(Store(CONFIG.db_path), CONFIG, a.limit)
    print(f"Scaricati {n} messaggi dal canale {CONFIG.channel_id}.")


def cmd_import(a):
    from pathlib import Path

    from .importer import import_export
    n, authors = import_export(Path(a.file), Store(CONFIG.db_path))
    print(f"Importati {n} messaggi. Autori:")
    for k, v in list(authors.items())[:10]:
        print(f"  {v:>5}  {k}")
    print("Imposta CHENTO_AUTHOR_ID con l'ID di Chento, poi: python -m chento analyze")


def cmd_analyze(a):
    from .market import Market
    from .pipeline import analyze, export
    store = Store(CONFIG.db_path)
    data = analyze(store, Market(), use_ai=not a.no_ai)
    path = export(data)
    r, d = data["replica"]["stats"], data["derived"]["stats"]
    print(f"Messaggi analizzati: {data['profile']['activity']['messages']}  ·  segnali: {r['signals']}")
    print(f"Strategia rilevata: {data['profile']['fingerprint']['summary']}")
    for name, s in (("Replica Chento", r), ("Chento+       ", d)):
        print(f"  {name}  trade {s['closed']:>3}  WR {s['win_rate']}%  avg {s['avg_r']}R  tot {s['total_r']}R  "
              f"PF {s['profit_factor']}  DD {s['max_dd_r']}R")
    print(f"Dashboard aggiornata: {path}")


def cmd_watch(a):
    from .alerts import build_alert, console, send_webhook
    from .discord_fetch import DiscordClient, fetch_new, is_target_author
    from .market import Market
    from .pipeline import analyze, export, extract
    store, market = Store(CONFIG.db_path), Market()
    client = DiscordClient(CONFIG)
    data = analyze(store, market, use_ai=not a.no_ai)
    export(data)
    replica = data["replica"]["trades"]
    print(f"In ascolto su canale {CONFIG.channel_id} (poll {CONFIG.poll_seconds}s). Ctrl+C per uscire.")
    while True:
        try:
            new = [m for m in fetch_new(store, client, CONFIG) if is_target_author(m)]
        except Exception as e:  # rete instabile: riprova al giro successivo
            print(f"[watch] errore: {e}")
            new = []
        for m in new:
            sig = extract(store, m, use_ai=not a.no_ai)
            al = build_alert(m, sig, replica, market)
            store.save_alert(m["id"], m["ts"], al)
            print(console(al))
            send_webhook(al)
        if new:
            data = analyze(store, market, use_ai=not a.no_ai, ensure_alerts=False)
            export(data)
            replica = data["replica"]["trades"]
        time.sleep(CONFIG.poll_seconds)


def cmd_demo(a):
    from .demo import build
    from .market import Market
    n = build(Store(CONFIG.db_path), Market(), n_signals=a.signals)
    print(f"Creati {n} messaggi DEMO sintetici. Ora esegui: python -m chento analyze")


def cmd_serve(a):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    print(f"Dashboard: http://localhost:{a.port}/dashboard/")
    http.server.ThreadingHTTPServer(("0.0.0.0", a.port), handler).serve_forever()


def main():
    p = argparse.ArgumentParser(prog="chento", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    sub.add_parser("logout").set_defaults(fn=cmd_logout)
    s = sub.add_parser("sync")
    s.add_argument("--limit", type=int, default=None, help="massimo numero di messaggi")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("import")
    s.add_argument("file", help="file .json esportato con DiscordChatExporter")
    s.set_defaults(fn=cmd_import)
    for name, fn in (("analyze", cmd_analyze), ("watch", cmd_watch)):
        s = sub.add_parser(name)
        s.add_argument("--no-ai", action="store_true", help="solo parser a regole, niente Claude")
        s.set_defaults(fn=fn)
    s = sub.add_parser("demo")
    s.add_argument("--signals", type=int, default=45)
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

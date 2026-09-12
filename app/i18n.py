"""Traduzioni del bot Telegram (SOLO italiano).

La lingua è bloccata all'italiano per tutti gli utenti.
"""
import logging

from app.core import kv

log = logging.getLogger("i18n")

T = {
    "it": {
        "menu_title": ("📊 Serie A Stats — tutto gratis, ogni giorno\n\n"
                       "⚽ Classifica, partite, risultati e LIVE\n"
                       "💰 Pronostici del modello (1X2 · Over/Under · BTTS)\n"
                       "✨ Tiri in porta, giocatori e analisi squadre\n\n"
                       "Tocca un bottone qui sotto oppure scrivimi una domanda "
                       "libera (es. \"chi vince Inter - Milan?\")."),
        "menu_classifica": "🏆 Classifica",
        "menu_partite": "⚽ Prossime partite",
        "menu_risultati": "📋 Risultati",
        "menu_live": "🔴 LIVE",
        "menu_pronostici": "💰 Pronostici",
        "menu_tiri": "🎯 Tiri in porta",
        "menu_tirigiocatori": "✨ Tiri giocatori",
        "menu_arbitri": "👮 Arbitri",
        "menu_tracking": "📊 Onestà modello",
        "menu_segui": "🔔 Segui squadra",
        "menu_stopsegui": "🔕 Ferma follow",
        "menu_donazioni": "⭐ Donazioni",
        "menu_menu": "🏠 Menu",
        "disclaimer": ("⚠️ I pronostici sono SOLO stime statistiche, NON sono consigli "
                       "finanziari né risultati sicuri: anche il modello sbaglia. "
                       "Scommetti con giudizio, per divertimento e solo ciò che puoi "
                       "perdere. Gioco riservato ai maggiorenni."),
        "subs_coupon_ok": "🎉 Coupon validissimo: hai il completo ⭐ a VITA!\nOra vedi tutti i pronostici. Grazie!",
        "subs_coupon_bad": "❌ Codice non valido o già riscattato.",
        "prono_nodata": "Nessun pronostico disponibile al momento.",
        "back": "◀ Indietro",
        "all": "Tutte",
        "classifica_title": "🏆 Classifica Serie A",
        "classifica_nodata": "Nessun dato classifica.",
        "classifica_row": "{pos}. {name}  {points} pt ({played} g, {gf}-{ga})",
        "partite_title": "⚽ Prossime partite (giornata {r}):",
        "partite_nodata": "Nessuna partita programmata.",
        "partite_value": "valore +{edge:.0f}%",
        "risultati_title": "📋 Risultati Serie A",
        "risultati_nodata": "Nessun risultato ancora disponibile.",
        "giornata": "GIORNATA {r}",
        "live_title": "🔴 LIVE Serie A",
        "live_nodata": ("Nessun match live in questo momento.\n"
                        "Usa 📋 Risultati per vedere le ultime giornate."),
        "shots_title": "✨ Tiri in porta giocatori (giornata {r}):",
        "shots_nodata": "Nessun dato sui tiri dei giocatori disponibile.",
        "shots_player": "  • {name} {avg} a gara ({played} g) · 💥 {threat}/10 · Over1,5 @{o15}",
        "menu_morale": "🎭 Morale & conferenze",
        "menu_marcatori": "⚽ Marcatori",
        "morale_title": "🎭 Morale pre-partita (giornata {r}):",
        "morale_nodata": "Nessun dato sul morale disponibile.",
        "pronostici_note": "🎯 Centratura modello: {hit}/{tot} pronostici valutati ({rate:.0f}%).",
        "segui_prompt": "Scegli la squadra da seguire 👇\nRiceverai avvisi a inizio partita, a ogni gol e a fine gara.",
        "segui_ok": "🔔 Ora seguo: {teams}\nTi avviserò a inizio partita, a ogni gol e a fine gara.",
        "stop_prompt": "Quali squadre smettere di seguire? 👇",
        "stop_ok_all": "🔕 Ho rimosso tutte le squadre seguite.",
        "stop_ok": "🔕 Rimosso: {teams}",
        "stop_none": "Non segui nessuna squadra. Usa 🔔 Segui squadra dal menu.",
        "tracking_title": "📊 Onestà del modello",
        "tracking_empty": "Nessun pronostico ancora valutato: partirà con i prossimi risultati.",
        "tracking_evaluated": "Partite valutate: {n}",
        "tracking_hit": "Indovinati: {hit}/{tot} ({pct:.0f}%)",
        "tracking_brier": "Brier score: {b:.3f} (più basso = più onesto)",
        "tracking_rps": "RPS 1X2: {r:.4f} (più basso = più onesto)",
        "tracking_oos": "Fuori campione (solo round precedenti): Brier {b:.3f} → {bc:.3f} ({imp:+.3f})",
        "tracking_oos_rps": "RPS OOS: {r:.3f} → {rc:.3f}",
        "tracking_oos_ci": "CI95 miglioramento {imp:+.3f}: {lo:+.3f}…{hi:+.3f} (p_better {p:.2f}) {sig}",
        "tracking_oos_picks": "Pronostici modello OOS: {hit}/{tot} ({pct:.0f}%)",
        "tracking_learned": "Cosa ho imparato:",
        "market_1x2": "1X2",
        "market_over_under": "Over/Under 2.5",
        "market_btts": "Entrambe a segno",
        "pronostico_pick": "Pronostico del modello: {pick} ({pct:.0f}%)",
        "pronostico_exact": "Risultato esatto più probabile: {score} ({pct:.0f}%)",
        "pronostico_saves": "🧤 {gk} ({team}): ~{exp} parate · Over {thr:g} @{fair} ({pct:.0f}%)",
        "pronostico_tipster": "🔁 Voce esterna {src} (affid. {rate}): 1X2 {o} · O/U {g} · {s}",
        "don_title": ("⭐ Sostieni Serie A Stats\n\n"
                      "Scegli un importo in Telegram Stars.\n"
                      "Ogni stella aiuta a mantenere il bot sempre attivo. Grazie!"),
        "don_thanks": "🙏 Grazie mille per il supporto! ({stars} ⭐)",
        "ai_thinking": "⏳ Analizzo i dati…",
        "marcatori_title": "⚽ Probabilità marcatori (giornata {r}):",
        "marcatori_nodata": "Nessun dato marcatori disponibile.",
        "marcatori_player": "  • {name} ({pos}) · {prob}% · {goals} gol ultime {matches} gare · SOT: {sot}",
        "marcatori_opp": "Difesa avversaria: {opp} gol subiti a gara",
    },
}

DONATION_OPTIONS = (10, 25, 50, 100, 200, 500)


def _tr(language, key, **kw):
    table = T.get(language, T["it"])
    text = table.get(key, T["it"].get(key, key))
    if kw:
        try:
            return text.format(**kw)
        except KeyError:
            return text
    return text


class Tr:
    """Helper di traduzione di una chat (bloccato all'italiano)."""
    def __init__(self, chat_id):
        self.lang = "it"

    def _t(self, key, **kwargs):
        return _tr(self.lang, key, **kwargs)
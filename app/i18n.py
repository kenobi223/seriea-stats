"""Traduzioni del bot Telegram (SOLO italiano).

La lingua è bloccata all'italiano per tutti gli utenti. I testi possono
contenere markup HTML (parse_mode="HTML"): i dinamici vanno escapati prima.
"""
import logging

from app.core import kv

log = logging.getLogger("i18n")

T = {
    "it": {
        "menu_title": ("<b>📊 Serie A Stats</b>\n"
                       "Tutto gratis, ogni giorno.\n\n"
                       "⚽ Classifica, partite, risultati e LIVE\n"
                       "🎯 Pronostici del modello: 1X2 · Over/Under · BTTS\n"
                       "🎫 Schedina della giornata con quote\n\n"
                       "Tocca un bottone qui sotto oppure scrivimi una domanda "
                       "libera (es. <i>chi vince Inter - Milan?</i>)."),
        "menu_classifica": "🏆 Classifica",
        "menu_partite": "⚽ Prossime partite",
        "menu_risultati": "📋 Risultati",
        "menu_live": "🔴 LIVE",
        "menu_pronostici": "💰 Pronostici",
        "menu_presagi": "🎯 Presagi",
        "menu_schedina": "🎫 Schedina giornata",
        "menu_tracking": "📊 Onestà modello",
        "menu_segui": "🔔 Segui squadra",
        "menu_stopsegui": "🔕 Ferma follow",
        "menu_donazioni": "⭐ Donazioni",
        "menu_sito": "🌐 Vai al sito web",
        "menu_menu": "🏠 Menu",
        "section_refresh": "🔄 Aggiorna",
        "disclaimer": ("⚠️ Stime statistiche, non consigli finanziari: anche il "
                       "modello sbaglia. Gioca con giudizio, solo ciò che puoi "
                       "perdere. 18+."),
        "subs_coupon_ok": "🎉 Coupon validissimo: hai il completo ⭐ a VITA!\nOra vedi tutti i pronostici. Grazie!",
        "subs_coupon_bad": "❌ Codice non valido o già riscattato.",
        "prono_nodata": "Nessun pronostico disponibile al momento.",
        "back": "◀ Indietro",
        "all": "Tutte",
        "classifica_title": "<b>🏆 Classifica Serie A</b>",
        "classifica_nodata": "Nessun dato classifica.",
        "classifica_row": "{pos}. {name}  {points} pt ({played} g, {gf}-{ga})",
        "partite_title": "<b>⚽ Prossime partite — giornata {r}</b>",
        "partite_nodata": "Nessuna partita programmata.",
        "partite_value": "valore +{edge:.0f}%",
        "risultati_title": "<b>📋 Risultati Serie A</b>",
        "risultati_nodata": "Nessun risultato ancora disponibile.",
        "giornata": "<b>GIORNATA {r}</b>",
        "live_title": "<b>🔴 LIVE Serie A</b>",
        "live_nodata": ("Nessun match live in questo momento.\n"
                        "Usa 📋 Risultati per vedere le ultime giornate."),
        "menu_morale": "🎭 Morale & conferenze",
        "morale_title": "<b>🎭 Morale pre-partita — giornata {r}</b>",
        "morale_nodata": "Nessun dato sul morale disponibile.",
        "pronostici_note": "🎯 Centratura modello: {hit}/{tot} pronostici valutati ({rate:.0f}%).",
        "segui_prompt": "Scegli la squadra da seguire 👇\nRiceverai avvisi a inizio partita, a ogni gol e a fine gara.",
        "segui_ok": "🔔 Ora seguo: {teams}\nTi avviserò a inizio partita, a ogni gol e a fine gara.",
        "stop_prompt": "Quali squadre smettere di seguire? 👇",
        "stop_ok_all": "🔕 Ho rimosso tutte le squadre seguite.",
        "stop_ok": "🔕 Rimosso: {teams}",
        "stop_none": "Non segui nessuna squadra. Usa 🔔 Segui squadra dal menu.",
        "tracking_title": "<b>📊 Onestà del modello</b>",
        "tracking_empty": "Nessun pronostico ancora valutato: partirà con i prossimi risultati.",
        "tracking_evaluated": "Partite valutate: {n}",
        "tracking_hit": "Indovinati: {hit}/{tot} ({pct:.0f}%)",
        "tracking_match_hit": "Partite con pronostico vinto: {hit}/{tot} ({pct:.0f}%)",
        "tracking_brier": "Brier score: {b:.3f} (più basso = più onesto)",
        "tracking_rps": "RPS 1X2: {r:.4f} (più basso = più onesto)",
        "tracking_oos": "Fuori campione (solo round precedenti): Brier {b:.3f} → {bc:.3f} ({imp:+.3f})",
        "tracking_oos_rps": "RPS OOS: {r:.3f} → {rc:.3f}",
        "tracking_oos_ci": "CI95 miglioramento {imp:+.3f}: {lo:+.3f}…{hi:+.3f} (p_better {p:.2f}) {sig}",
        "tracking_oos_picks": "Pronostici modello OOS: {hit}/{tot} ({pct:.0f}%)",
        "tracking_learned": "<b>Cosa ho imparato:</b>",
        "market_1x2": "1X2",
        "market_over_under": "Over/Under 2.5",
        "market_btts": "Entrambe a segno",
        "pronostico_pick": "Pronostico: {pick} ({pct:.0f}%)",
        "pronostico_exact": "Risultato esatto più probabile: {score} ({pct:.0f}%)",
        "pronostico_tipster": "🔁 Voce esterna {src} (affid. {rate}): 1X2 {o} · O/U {g} · {s}",
        "presagi_title": ("<b>🎯 Presagi del giorno</b>\n"
                          "Gli esiti più sicuri del modello: quota bookmaker "
                          "vs quota fair.\n"),
        "presagi_empty": ("Nessun presagio pronto: escono con i pronostici "
                          "della giornata. Riprova più tardi."),
        "digest_title": "<b>📅 Giornata {r} — oggi si gioca</b>",
        "digest_sub": "Le partite che restano, con il pronostico del modello:",
        "recap_title": "<b>🔮 Promemoria — le tue squadre</b>",
        "don_title": ("<b>⭐ Sostieni Serie A Stats</b>\n\n"
                      "Il bot è gratis e lo resta. Le donazioni pagano server, "
                      "fonti dati e nuove funzioni.\n\n"
                      "Scegli un importo in ⭐ Telegram Stars — bastano anche 10.\n"
                      "<b>Grazie di cuore.</b>"),
        "don_thanks": ("<b>❤️ Grazie, sei un campione!</b>\n\n"
                       "Hai donato <b>{stars} ⭐</b>. Contribuisci a tenere vivo "
                       "Serie A Stats: server, dati e sviluppo.\n\n"
                       "Il tuo nome entra nel libro dei sostenitori del bot."),
        "don_error": ("<b>❌ Donazione non riuscita</b>\n\n"
                      "Telegram ha risposto: <code>{err}</code>\n\n"
                      "Riprova tra qualche istante, se persiste scrivi al "
                      "proprietario del bot."),
        "don_invoice_title": "Donazione Serie A Stats",
        "ai_thinking": "⏳ Analizzo i dati…",
        "schedina_title": "<b>🎫 Schedina giornata {r}</b>",
        "schedina_nodata": "Nessuna schedina ancora pronta: la creo prima della prima partita della giornata.",
        "schedina_win": "✔ {pick} @ {odds}  [{pct:.0f}%]  {score} ✅",
        "schedina_loss": "✘ {pick} @ {odds}  [{pct:.0f}%]  {score} ❌",
        "schedina_pending": "◻ {pick} @ {odds}  [{pct:.0f}%]  ⏳",
        "schedina_counter": "<b>Combinata: {wins} vinti · {losses} persi</b>",
        "schedina_history_title": "<b>📚 Schedine passate:</b>",
        "schedina_history_row": "Giornata {r}: {wins} vinti · {losses} persi",
        "schedina_match": "<b>{home} - {away}</b>",
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

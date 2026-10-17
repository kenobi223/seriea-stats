# /aiuto — elenco comandi
def aiuto(message, u, text, command, args, call, params):
    bot.replyText(u, "\n".join([
        "<b>Comandi</b>",
        "/schedina — esiti della giornata",
        "/pronostici — probabilità e value bet",
        "/classifica — classifica Serie A",
        "/risultati — ultime giornate",
        "/aiuto — questo menu",
    ]))

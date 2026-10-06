/**
 * Modulo lip-sync italiano per TalkingHead.
 * Grafemi italiani → viseme Oculus (aa, E, I, O, U, PP, FF, DD, kk, CH, SS, nn, RR).
 * Struttura compatibile con lipsync-fi.mjs / lipsync-en.mjs.
 */
export class LipsyncIt {
  constructor() {
    this.visemes = {
      'a': 'aa', 'e': 'E', 'i': 'I', 'o': 'O', 'u': 'U',
      'b': 'PP', 'm': 'PP', 'p': 'PP',
      'f': 'FF', 'v': 'FF', 'w': 'FF',
      'd': 'DD', 't': 'DD',
      'g': 'kk', 'c': 'kk', 'k': 'kk', 'q': 'kk',
      'l': 'nn', 'n': 'nn',
      'r': 'RR',
      's': 'SS', 'z': 'SS', 'x': 'SS',
      'j': 'I', 'y': 'I'
    };
    this.visemeDurations = {
      'aa': 0.95, 'E': 0.90, 'I': 0.85, 'O': 0.95, 'U': 0.90,
      'PP': 1.05, 'SS': 1.15, 'DD': 1.00, 'FF': 1.00, 'kk': 1.10,
      'CH': 1.05, 'nn': 0.85, 'RR': 0.90, 'sil': 1
    };
    this.specialDurations = {
      ' ': 1, ',': 3, '.': 3, '!': 3, '?': 3, ';': 2, ':': 2, '-': 0.5, "'": 0.25
    };
    this.numbers = [
      'zero', 'uno', 'due', 'tre', 'quattro', 'cinque', 'sei', 'sette',
      'otto', 'nove', 'dieci', 'undici', 'dodici', 'tredici', 'quattordici',
      'quindici', 'sedici', 'diciassette', 'diciotto', 'diciannove'
    ];
    this.tens = ['', '', 'venti', 'trenta', 'quaranta', 'cinquanta', 'sessanta', 'settanta', 'ottanta', 'novanta'];
    this.symbols = {
      '%': ' per cento ', '€': ' euro ', '£': ' sterline ', '&': ' e ',
      '+': ' più ', '$': ' dollari ', '@': ' chiocciola ', '#': ' cancelletto '
    };
    this.symbolsReg = /[%€&+$@#£]/g;
  }

  /**
   * Converte un intero in parole italiane (fino ai milioni).
   * @param {string|number} x
   * @return {string}
   */
  numberToItalianWords(x) {
    let n = parseInt(x, 10);
    if (isNaN(n)) return String(x);
    let neg = '';
    if (n < 0) { neg = 'meno '; n = -n; }
    const under = (m) => {
      if (m < 20) return this.numbers[m];
      if (m < 100) {
        const t = this.tens[Math.floor(m / 10)];
        const u = m % 10;
        if (!u) return t;
        const uw = this.numbers[u];
        // elisione: venti+uno → ventuno, trenta+otto → trentotto
        if (uw[0] === 'o' || uw[0] === 'u') return t.slice(0, -1) + uw;
        return t + uw;
      }
      const r = m % 100;
      if (!r) return 'cento';
      const rw = under(r);
      // cento+otto → centotto, cento+ottanta → centottanta
      return (rw.startsWith('ott') ? 'cent' : 'cento') + rw;
    };
    if (n === 0) return 'zero';
    const out = [];
    if (n >= 1000000) {
      const mil = Math.floor(n / 1000000);
      out.push((mil === 1 ? 'un milione' : under(mil) + ' milioni'));
      n %= 1000000;
    }
    if (n >= 1000) {
      const t = Math.floor(n / 1000);
      out.push(t === 1 ? 'mille' : under(t) + 'mila');
      n %= 1000;
    }
    if (n > 0) out.push(under(n));
    return neg + out.join('');
  }

  /**
   * Normalizza il testo per il lip-sync: simboli, numeri, accenti.
   * @param {string} s
   * @return {string}
   */
  preProcessText(s) {
    return String(s)
      .replace(/[#_*":;()\[\]]/g, '')
      .replace(this.symbolsReg, (m) => this.symbols[m] || ' ')
      .replace(/(\d)\s*[.,]\s*(\d)/g, '$1 virgola $2')
      .replace(/\d+/g, (m) => this.numberToItalianWords(m))
      .replace(/\s+/g, ' ')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .normalize('NFC')
      .trim();
  }

  /**
   * Converte una parola in viseme Oculus con tempi relativi.
   * @param {string} w
   * @return {{words:string, visemes:string[], times:number[], durations:number[]}}
   */
  wordsToVisemes(w) {
    const o = { words: w, visemes: [], times: [], durations: [] };
    let t = 0;
    const chars = Array.from(String(w));
    const add = (v) => {
      if (!v) return;
      const d = this.visemeDurations[v] || 1;
      if (o.visemes.length && o.visemes[o.visemes.length - 1] === v) {
        const extra = d * 0.7;
        o.durations[o.durations.length - 1] += extra;
        t += extra;
      } else {
        o.visemes.push(v);
        o.times.push(t);
        o.durations.push(d);
        t += d;
      }
    };
    for (let i = 0; i < chars.length; i++) {
      const c = chars[i].toLowerCase();
      const n1 = (chars[i + 1] || '').toLowerCase();
      const n2 = (chars[i + 2] || '').toLowerCase();
      // sc + e/i → /ʃ/ (scende, scienza): unico viseme SS, la vocale resta
      if (c === 's' && n1 === 'c' && (n2 === 'e' || n2 === 'i')) { add('SS'); i++; continue; }
      // gli → /ʎ/ (figlio,aglietto)
      if (c === 'g' && n1 === 'l' && n2 === 'i') { add('I'); i += 2; continue; }
      // gn → /ɲ/ (gnocchi)
      if (c === 'g' && n1 === 'n') { add('nn'); i++; continue; }
      // ch/gh duri (che, chi, ghiaccio)
      if ((c === 'c' || c === 'g') && n1 === 'h') { add('kk'); i++; continue; }
      // ce/ci → /tʃ/ (cento, cinema), ge/gi → /dʒ/ (gelo, giro)
      if (c === 'c' && (n1 === 'e' || n1 === 'i')) { add('CH'); continue; }
      if (c === 'g' && (n1 === 'e' || n1 === 'i')) { add('CH'); continue; }
      // h muta (hotel, farlo)
      if (c === 'h') continue;
      const v = this.visemes[c];
      if (v) {
        add(v);
      } else {
        const d = this.specialDurations[chars[i]] || 0;
        if (d) t += d;
      }
    }
    return o;
  }
}

export default LipsyncIt;

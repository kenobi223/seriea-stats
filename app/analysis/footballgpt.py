"""Integrazione FootballGPT XGBoost nel nostro predictor.

Usa i modelli pre-trained (XGBoost + Decision Tree) per generare
predizioni 1x2 che vengono blenate con il nostro modello Poisson.

Fonte: https://github.com/FootballGPT/football-ai (MIT License)
"""
import logging
import os
import pathlib
import pickle
import warnings

import numpy as np
import pandas as pd
from scipy.stats import linregress

log = logging.getLogger("footballgpt")

_MODELS_DIR = pathlib.Path(__file__).parent / "models"
_xgb_model = None
_tree_model = None
_dicts = None


def _load_models():
    global _xgb_model, _tree_model, __dicts
    if _xgb_model is not None:
        return True
    try:
        with open(_MODELS_DIR / "xgb_model.pkl", "rb") as f:
            _xgb_model = pickle.load(f)
        with open(_MODELS_DIR / "tree_model.pkl", "rb") as f:
            _tree_model = pickle.load(f)
        with open(_MODELS_DIR / "dicts2translate.pkl", "rb") as f:
            _dicts = pickle.load(f)
        log.info("FootballGPT: modelli caricati")
        return True
    except Exception as e:
        log.warning("FootballGPT: errore caricamento modelli: %s", e)
        return False


def _wspolczynnik_zmiennosci(x):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = np.mean(x)
        if m == 0:
            return 0.0
        return np.mean(np.std(x) / m)


def _trend(x):
    if len(x) < 2:
        return 0.0
    slope, _, _, _, _ = linregress(np.arange(len(x)), x)
    return slope


def _create_agg_var(results):
    """Crea 198 variabili aggregate (rolling 3/5/7) per ogni squadra."""
    stats_map = {
        "avg": np.mean, "std": np.std, "wz": _wspolczynnik_zmiennosci,
        "max": np.max, "min": np.min, "trd": _trend,
    }
    windows = [3, 5, 7]
    base_vars = [
        "pts", "goal_zdob", "goal_strc", "sh_odd", "sh_otrz",
        "sot_odd", "sot_otrz", "cor_wyk", "cor_bro", "yel_card", "red_card",
    ]

    grouped = [g for _, g in results.groupby("Team")]
    team_names = [name for name, _ in results.groupby("Team")]

    rows = []
    for team_data in grouped:
        row = {}
        for var in base_vars:
            vals = team_data[var].values
            for stat_name, stat_fn in stats_map.items():
                for w in windows:
                    col = f"{var}_{stat_name}{w}"
                    if len(vals) >= w:
                        row[col] = stat_fn(vals[:w])
                    else:
                        row[col] = stat_fn(vals) if len(vals) > 0 else 0.0
        rows.append(row)

    form_var = pd.DataFrame(rows, index=team_names)
    return form_var


def predict_match(home_team, away_team, matches_df):
    """Predice esito partita usando il modello FootballGPT.

    Args:
        home_team: nome squadra di casa (formato nostro)
        away_team: nome squadra ospite
        matches_df: DataFrame con storico partite con colonne:
            HomeTeam, AwayTeam, FTHG, FTAG, FTR, HS, AS, HST, AST, HC, AC, HY, AY, HR, AR

    Returns:
        dict con {"home": float, "draw": float, "away": float, "prediction": str}
        o None se errore
    """
    if not _load_models():
        return None

    if matches_df is None or len(matches_df) < 7:
        log.warning("FootballGPT: insufficiente storico (%s matches)", len(matches_df) if matches_df is not None else 0)
        return None

    try:
        results = matches_df.copy()
        required = ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HS", "AS", "HST", "AST", "HC", "AC", "HY", "AY", "HR", "AR"]
        for col in required:
            if col not in results.columns:
                log.warning("FootballGPT: colonna %s mancante", col)
                return None

        # duplica视角 (home + away)
        results2 = results.copy()
        results2 = results2.drop(["HomeTeam"], axis=1)
        results2["HomeTeam"] = results2.AwayTeam
        results2 = results2.drop(["AwayTeam"], axis=1)
        results2["HoA"] = "A"
        results["HoA"] = "H"
        results = results.drop(["AwayTeam"], axis=1)
        results = pd.concat([results, results2], axis=0, ignore_index=True)
        results.rename(columns={"HomeTeam": "Team"}, inplace=True)
        results = results.sort_values(by=["Date"] if "Date" in results.columns else results.columns[0], ascending=False)

        def pts_fn(r):
            if r.FTR == "D": return 1
            if r.FTR == r.HoA: return 3
            return 0

        def col_fn(r, if_a, if_h):
            return r[if_a] if r.HoA == "A" else r[if_h]

        results["pts"] = results.apply(pts_fn, axis=1)
        results["goal_zdob"] = results.apply(lambda x: col_fn(x, "FTAG", "FTHG"), axis=1)
        results["goal_strc"] = results.apply(lambda x: col_fn(x, "FTHG", "FTAG"), axis=1)
        results["sh_odd"] = results.apply(lambda x: col_fn(x, "AS", "HS"), axis=1)
        results["sh_otrz"] = results.apply(lambda x: col_fn(x, "HS", "AS"), axis=1)
        results["sot_odd"] = results.apply(lambda x: col_fn(x, "AST", "HST"), axis=1)
        results["sot_otrz"] = results.apply(lambda x: col_fn(x, "HST", "AST"), axis=1)
        results["cor_wyk"] = results.apply(lambda x: col_fn(x, "AC", "HC"), axis=1)
        results["cor_bro"] = results.apply(lambda x: col_fn(x, "HC", "AC"), axis=1)
        results["yel_card"] = results.apply(lambda x: col_fn(x, "AY", "HY"), axis=1)
        results["red_card"] = results.apply(lambda x: col_fn(x, "HR", "AR"), axis=1)

        form_var = _create_agg_var(results)

        # league table
        raw = matches_df.copy()
        raw["H_pts"] = raw["FTR"].map({"H": 3, "A": 0, "D": 1})
        raw["A_pts"] = raw["FTR"].map({"H": 0, "A": 3, "D": 1})

        home_t = raw.groupby("HomeTeam").sum(numeric_only=True)[["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "H_pts"]]
        away_t = raw.groupby("AwayTeam").sum(numeric_only=True)[["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "A_pts"]]
        home_t.columns = ["H_gz", "H_gs", "H_sh", "H_sha", "H_sot", "H_sota", "H_cw", "H_cb", "H_pts"]
        away_t.columns = ["A_gs", "A_gz", "A_sha", "A_sh", "A_sota", "A_sot", "A_cb", "A_cw", "A_pts"]

        res_t = pd.concat([home_t, away_t], axis=1)
        res_t["gz"] = res_t.H_gz + res_t.A_gz
        res_t["gs"] = res_t.H_gs + res_t.A_gs
        res_t["bilans"] = res_t.gz - res_t.gs
        res_t["pts"] = res_t.H_pts + res_t.A_pts
        res_t["n_match"] = raw.groupby("HomeTeam").size().reindex(res_t.index).fillna(0) + raw.groupby("AwayTeam").size().reindex(res_t.index).fillna(0)
        res_t["n_match"] = res_t["n_match"].replace(0, 1)

        res_t.sort_values(by=["pts", "bilans", "gz"], ascending=(False, False, False), inplace=True)

        res_t["pts_per_math"] = res_t.pts / res_t.n_match
        res_t["gz_m"] = res_t.gz / res_t.n_match
        res_t["gs_m"] = res_t.gs / res_t.n_match
        res_t["sh_od"] = (res_t.H_sh + res_t.A_sha) / res_t.n_match
        res_t["sh_ot"] = (res_t.H_sha + res_t.A_sh) / res_t.n_match
        res_t["cw"] = (res_t.H_cw + res_t.A_cw) / res_t.n_match
        res_t["cb"] = (res_t.H_cb + res_t.A_cb) / res_t.n_match
        res_t["pozycja"] = range(1, len(res_t) + 1)

        # FIFA ratings
        fifa_path = _MODELS_DIR / "fifa_rating_SerieA.csv"
        if fifa_path.exists():
            fifa = pd.read_csv(fifa_path, sep=";")
            fifa = fifa.set_index("Name")
        else:
            fifa = pd.DataFrame(index=res_t.index)
            fifa["ATT"] = 75
            fifa["MID"] = 75
            fifa["DEF"] = 75
            fifa["OVR"] = 75

        output = pd.concat([
            form_var,
            res_t[["pts_per_math", "gz_m", "gs_m", "sh_od", "sh_ot", "cw", "cb", "pozycja"]],
            fifa
        ], axis=1)

        # mappa nomi squadre (nostro -> FootballGPT)
        name_map = _get_name_map()
        h_name = name_map.get(home_team, home_team)
        a_name = name_map.get(away_team, away_team)

        if h_name not in output.index or a_name not in output.index:
            log.warning("FootballGPT: squadra non trovata: %s o %s", h_name, a_name)
            return None

        h_var = output.loc[[h_name], :].copy()
        h_var.columns = ["h_" + i for i in h_var.columns]
        h_var.index = [0]

        a_var = output.loc[[a_name], :].copy()
        a_var.columns = ["a_" + i for i in a_var.columns]
        a_var.index = [0]

        features = pd.concat([h_var, a_var], axis=1)
        features["position_dst"] = abs(features["h_pozycja"] - features["a_pozycja"])
        features["ATT_dst"] = abs(features.get("h_ATT", 75) - features.get("a_ATT", 75))
        features["MID_dst"] = abs(features.get("h_MID", 75) - features.get("a_MID", 75))
        features["DEF_dst"] = abs(features.get("h_DEF", 75) - features.get("a_DEF", 75))
        features["OVR_dst"] = abs(features.get("h_OVR", 75) - features.get("a_OVR", 75))

        # predizione
        probs = _xgb_model.predict_proba(features)[0]
        tree_pred = _tree_model.predict(pd.DataFrame([probs]))[0]
        prediction = _dicts["idx2str"].get(tree_pred, "?")

        result = {
            "home": round(float(probs[0]), 3),
            "draw": round(float(probs[1]), 3),
            "away": round(float(probs[2]), 3),
            "prediction": prediction,
        }
        log.info("FootballGPT: %s vs %s -> %s (%.1f%%/%.1f%%/%.1f%%)",
                 home_team, away_team, prediction,
                 result["home"] * 100, result["draw"] * 100, result["away"] * 100)
        return result

    except Exception as e:
        log.warning("FootballGPT: errore predizione %s vs %s: %s", home_team, away_team, e)
        return None


def _get_name_map():
    """Mappa nomi nostri -> nomi FootballGPT per Serie A."""
    return {
        "Atalanta": "Atalanta",
        "Bologna": "Bologna",
        "Cagliari": "Cagliari",
        "Empoli": "Empoli",
        "Fiorentina": "Fiorentina",
        "Genoa": "Genoa",
        "Hellas Verona": "Verona",
        "Verona": "Verona",
        "Inter": "Inter",
        "Internazionale": "Inter",
        "Juventus": "Juventus",
        "Lazio": "Lazio",
        "Lecce": "Lecce",
        "AC Milan": "Milan",
        "Milan": "Milan",
        "Monza": "Monza",
        "Napoli": "Napoli",
        "Parma": "Parma",
        "AS Roma": "Roma",
        "Roma": "Roma",
        "Salernitana": "Salernitana",
        "Sassuolo": "Sassuolo",
        "Torino": "Torino",
        "Udinese": "Udinese",
    }

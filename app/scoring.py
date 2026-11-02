"""Chargement des données et calcul des scores des stations."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"

CRITERES = {
    "prix": "Prix",
    "ski": "Domaine skiable",
    "climat": "Climat / enneigement",
    "rdt": "Rentabilité",
    "acces": "Accès",
    "vie": "Vie 4 saisons",
}
PROFILS = {
    "Usage perso": {"prix": 20, "ski": 25, "climat": 20, "rdt": 5, "acces": 15, "vie": 15},
    "Mixte": {"prix": 20, "ski": 20, "climat": 20, "rdt": 20, "acces": 10, "vie": 10},
    "Locatif": {"prix": 20, "ski": 15, "climat": 15, "rdt": 35, "acces": 10, "vie": 5},
}
# Écart de temps de trajet par rapport à Lyon (heures)
DEPARTS = {"Lyon": 0.0, "Paris (TGV)": 1.9, "Genève": -0.3, "Chambéry": -0.9, "Grenoble": -0.2}
FRAIS_NOTAIRE = 0.08
MIN_VENTES_DVF = 20


def clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def load_stations() -> pd.DataFrame:
    st = pd.read_csv(DATA / "stations.csv", sep=";")
    dvf_path = DATA / "dvf_stations.csv"
    if dvf_path.exists():
        st = st.merge(pd.read_csv(dvf_path), left_on="id", right_on="station_id", how="left")
    else:
        st["nb_ventes"] = 0
        st["prix_m2_median"] = None
    fiable = st["nb_ventes"].fillna(0) >= MIN_VENTES_DVF
    st["prix_source"] = fiable.map({True: "DVF", False: "Estimation"})
    st["prix_m2"] = st["prix_m2_median"].where(fiable, st["prix_estime"]).astype(float)
    st["forces"] = st["forces"].str.split("|")
    st["faiblesses"] = st["faiblesses"].str.split("|")
    return st


def load_maj() -> dict | None:
    path = DATA / "maj.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_ventes() -> pd.DataFrame:
    path = DATA / "dvf_ventes.csv"
    return pd.read_csv(path, parse_dates=["date_mutation"]) if path.exists() else pd.DataFrame()


def notes_criteres(s: pd.Series, depart: str) -> dict[str, float]:
    trajet = s.trajet_lyon_h + DEPARTS[depart]
    return {
        "prix": clamp(100 - (s.prix_m2 - 2500) / (14000 - 2500) * 100),
        "ski": clamp(math.log(s.km_pistes / 25) / math.log(600 / 25) * 100),
        "climat": clamp((s.alt_station - 1000) / (2300 - 1000) * 70 + (s.alt_max - 2000) / (3400 - 2000) * 30),
        "rdt": clamp((s.rdt_brut - 3) / (5.5 - 3) * 100),
        "acces": clamp(100 - (trajet - 1) / (4.5 - 1) * 100),
        "vie": float(s.vie),
    }


def indice_neige_2050(s: pd.Series) -> int:
    """Indice simplifié de fiabilité de l'enneigement à horizon 2050 (0-100), en attendant les données DRIAS."""
    return round(clamp((s.alt_station - 900) / 14 + (s.alt_max - 2000) / 40, 15, 98))


def scorer(st: pd.DataFrame, poids: dict[str, int], budget: float, surface_min: float, depart: str) -> pd.DataFrame:
    total_poids = sum(poids.values()) or 1
    rows = []
    for _, s in st.iterrows():
        notes = notes_criteres(s, depart)
        score = sum(notes[k] * poids[k] for k in CRITERES) / total_poids
        m2 = budget / (s.prix_m2 * (1 + FRAIS_NOTAIRE))
        rows.append({**{f"note_{k}": round(v) for k, v in notes.items()},
                     "score": round(score), "m2_budget": m2, "dans_budget": m2 >= surface_min,
                     "trajet_h": s.trajet_lyon_h + DEPARTS[depart], "neige_2050": indice_neige_2050(s)})
    out = pd.concat([st.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return out.sort_values(["dans_budget", "score"], ascending=[False, False]).reset_index(drop=True)


def simulation(prix: float, apport: float, taux_pct: float, duree_ans: int, rdt_brut: float, semaines: int,
               semaines_perso: int, charges: float, taxe_fonciere: float, tmi: float, classe: bool) -> dict:
    notaire = prix * FRAIS_NOTAIRE
    emprunt = max(0.0, prix + notaire - apport)
    t, n = taux_pct / 100 / 12, duree_ans * 12
    mensualite = emprunt * t / (1 - (1 + t) ** -n) if t else emprunt / n
    semaines_louees = max(0, semaines - semaines_perso)
    loyers = prix * rdt_brut / 100 * semaines_louees / semaines
    gestion = loyers * 0.22
    net = loyers - gestion - charges - taxe_fonciere
    cashflow = net / 12 - mensualite

    # Fiscalité LMNP la première année (estimation)
    ps = 0.172
    abattement, plafond = (0.5, 77_700) if classe else (0.3, 15_000)
    micro_ok = loyers <= plafond
    impot_micro = loyers * (1 - abattement) * (tmi + ps) if micro_ok else None
    interets = emprunt * taux_pct / 100
    amortissement = prix * 0.85 / 30 + 8000 / 7
    base_reel = net - interets - amortissement
    impot_reel = max(0.0, base_reel) * (tmi + ps)
    return {
        "notaire": notaire, "emprunt": emprunt, "mensualite": mensualite, "semaines_louees": semaines_louees,
        "loyers": loyers, "gestion": gestion, "net": net, "rendement_net": net / (prix + notaire) * 100,
        "cashflow": cashflow, "abattement": abattement, "impot_micro": impot_micro, "impot_reel": impot_reel,
        "deficit_reportable": max(0.0, -base_reel),
    }

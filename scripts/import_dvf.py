"""Télécharge les ventes DVF des communes de station et calcule les prix au m² par station.

Usage : python scripts/import_dvf.py [--refresh]
  --refresh   retélécharge les fichiers DVF au lieu d'utiliser le cache

Sorties :
  data/communes.csv       nom de commune -> code INSEE (via geo.api.gouv.fr)
  data/dvf_ventes.csv     ventes d'appartements retenues, rattachées à une station
  data/dvf_stations.csv   indicateurs de prix par station
  data/maj.json           date et périmètre de la dernière mise à jour
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Utilise le magasin de certificats du système (nécessaire derrière un proxy d'entreprise)
truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"
NB_ANNEES = 5
DVF_INDEX = "https://files.data.gouv.fr/geo-dvf/latest/csv/"
DVF_URL = DVF_INDEX + "{year}/communes/73/{code}.csv"
GEO_URL = "https://geo.api.gouv.fr/departements/73/communes"

# Seuils pour écarter les ventes atypiques (parkings mal typés, ventes en bloc...)
SURFACE_MIN, PRIX_M2_MIN, PRIX_M2_MAX = 12, 1000, 45000
# En dessous de ce nombre de ventes dans le rayon, on élargit à toute la commune
MIN_VENTES = 15


def distance_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def http() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


SESSION = http()


def normalise(nom: str) -> str:
    sans_accents = unicodedata.normalize("NFD", nom).encode("ascii", "ignore").decode()
    return "".join(c for c in sans_accents.lower() if c.isalnum())


def resolve_communes(noms: set[str]) -> dict[str, str]:
    r = SESSION.get(GEO_URL, params={"fields": "nom,code"}, timeout=60)
    r.raise_for_status()
    index = {normalise(c["nom"]): c["code"] for c in r.json()}
    manquantes = [n for n in noms if normalise(n) not in index]
    if manquantes:
        raise SystemExit(f"Communes introuvables en Savoie : {', '.join(manquantes)}")
    return {n: index[normalise(n)] for n in sorted(noms)}


def annees_disponibles() -> list[int]:
    """Les NB_ANNEES dernières années publiées dans DVF (détectées sur data.gouv.fr)."""
    r = SESSION.get(DVF_INDEX, timeout=60)
    r.raise_for_status()
    annees = sorted({int(a) for a in re.findall(r'href="[^"]*?/(\d{4})/"', r.text)})
    if not annees:
        raise SystemExit("Impossible de lire la liste des années DVF sur data.gouv.fr")
    return annees[-NB_ANNEES:]


def load_dvf(code: str, year: int, refresh: bool = False) -> pd.DataFrame | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{year}_{code}.csv"
    if refresh or not path.exists():
        r = SESSION.get(DVF_URL.format(year=year, code=code), timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        path.write_bytes(r.content)
    return pd.read_csv(path, dtype={"code_commune": str, "id_parcelle": str}, low_memory=False)


def ventes_appartements(df: pd.DataFrame) -> pd.DataFrame:
    """Garde les mutations qui portent sur un seul appartement (dépendances admises)."""
    df = df[df["nature_mutation"] == "Vente"]
    locaux = df[df["type_local"].isin(["Appartement", "Maison", "Local industriel. commercial ou assimilé"])]
    n_locaux = locaux.groupby("id_mutation").size()
    apparts = locaux[locaux["type_local"] == "Appartement"]
    apparts = apparts[apparts["id_mutation"].isin(n_locaux[n_locaux == 1].index)]
    apparts = apparts.drop_duplicates("id_mutation")
    apparts = apparts.dropna(subset=["valeur_fonciere", "surface_reelle_bati", "latitude", "longitude"])
    apparts = apparts[apparts["surface_reelle_bati"] >= SURFACE_MIN].copy()
    apparts["prix_m2"] = apparts["valeur_fonciere"] / apparts["surface_reelle_bati"]
    apparts = apparts[apparts["prix_m2"].between(PRIX_M2_MIN, PRIX_M2_MAX)]
    apparts["annee"] = apparts["date_mutation"].str[:4].astype(int)
    return apparts[["id_mutation", "date_mutation", "annee", "code_commune", "nom_commune", "valeur_fonciere",
                    "surface_reelle_bati", "nombre_pieces_principales", "prix_m2", "latitude", "longitude",
                    "adresse_nom_voie"]]


def main(refresh: bool = False, log=print, progression=None) -> dict:
    """Lance l'import. `log` reçoit les messages, `progression(fraction)` l'avancement entre 0 et 1."""
    stations = pd.read_csv(DATA / "stations.csv", sep=";")
    stations["communes_l"] = stations["communes"].str.split("|")

    log("Recherche des années publiées dans DVF…")
    years = annees_disponibles()
    log(f"Années retenues : {years[0]} à {years[-1]}")

    log("Résolution des codes communes…")
    noms = {c for lst in stations["communes_l"] for c in lst}
    codes = resolve_communes(noms)
    pd.DataFrame(sorted(codes.items()), columns=["commune", "code_insee"]).to_csv(DATA / "communes.csv", index=False)

    log("Téléchargement des ventes DVF…" if refresh else "Lecture des ventes DVF (cache)…")
    par_commune = {}
    for i, (nom, code) in enumerate(codes.items(), 1):
        frames = []
        for y in years:
            df = load_dvf(code, y, refresh)
            if df is not None:
                frames.append(ventes_appartements(df))
        par_commune[nom] = pd.concat(frames) if frames else pd.DataFrame()
        log(f"  {nom} ({code}) : {len(par_commune[nom])} ventes d'appartements")
        if progression:
            progression(i / len(codes))

    ventes, indic = [], []
    for s in stations.itertuples():
        pool = pd.concat([par_commune[c] for c in s.communes_l])
        d = pool.apply(lambda r: distance_km(s.lat, s.lon, r.latitude, r.longitude), axis=1) if len(pool) else pd.Series(dtype=float)
        dans_rayon = pool[d <= s.rayon_km]
        perimetre = "rayon"
        if len(dans_rayon) < MIN_VENTES:
            dans_rayon, perimetre = pool, "commune"
        v = dans_rayon.assign(station_id=s.id)
        ventes.append(v)

        # La dernière année publiée est souvent incomplète : les prix récents portent sur les deux dernières
        recent = v[v["annee"] >= years[-2]]
        med_an = v.groupby("annee")["prix_m2"].median()
        first, last = med_an.get(years[0]), med_an.get(years[-1], med_an.get(years[-2]))
        indic.append({
            "station_id": s.id,
            "perimetre": perimetre,
            "nb_ventes": len(v),
            "nb_ventes_recentes": len(recent),
            "prix_m2_median": round((recent if len(recent) >= 8 else v)["prix_m2"].median()) if len(v) else None,
            "evol_pct": round((last / first - 1) * 100, 1) if first and last else None,
            **{f"prix_{y}": round(med_an[y]) if y in med_an else None for y in years},
        })
        log(f"  {s.nom:<28} {perimetre:<8} {len(v):>4} ventes  médiane {indic[-1]['prix_m2_median']} €/m²")

    toutes = pd.concat(ventes)
    toutes.to_csv(DATA / "dvf_ventes.csv", index=False)
    pd.DataFrame(indic).to_csv(DATA / "dvf_stations.csv", index=False)
    maj = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "annees": years,
        "derniere_vente": toutes["date_mutation"].max(),
        "nb_ventes": int(len(toutes)),
        "telechargement": refresh,
    }
    (DATA / "maj.json").write_text(json.dumps(maj, ensure_ascii=False, indent=2), encoding="utf-8")
    log("Terminé.")
    return maj


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="retélécharge les fichiers DVF au lieu d'utiliser le cache")
    main(refresh=parser.parse_args().refresh)

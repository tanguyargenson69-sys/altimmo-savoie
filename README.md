# Altimmo Savoie

Prototype d'aide à la décision pour choisir où acheter un appartement au ski en Savoie.

## Installation

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Mettre à jour les prix (DVF)

Dans l'application : bouton **Mettre à jour les données** en bas du panneau latéral. La date et l'heure
de la dernière mise à jour s'affichent au-dessus du bouton et dans l'en-tête.

En ligne de commande :

```bash
.venv\Scripts\python.exe scripts\import_dvf.py --refresh
```

Sans `--refresh`, le script réutilise les fichiers en cache (utile après une modification de `stations.csv`).
Les 5 dernières années publiées sont détectées automatiquement sur data.gouv.fr.

Le script télécharge les ventes DVF 2021-2025 des communes de station (mises en cache dans `data/cache/`),
garde les ventes d'un appartement seul, puis rattache à chaque station les ventes situées dans son rayon
(`rayon_km` dans `stations.csv`). Sous 15 ventes, il élargit à toute la commune. Dans l'application,
une station avec moins de 20 ventes utilise le prix estimé `prix_estime`.

## Lancer l'application

```bash
.venv\Scripts\python.exe -m streamlit run app\app.py
```

## Mise en ligne (Streamlit Community Cloud)

1. Se connecter sur https://share.streamlit.io avec le compte GitHub.
2. **Create app** → dépôt `tanguyargenson69-sys/altimmo-savoie`, branche `main`, fichier principal `app/app.py`.
3. **Advanced settings** → Python 3.12 ou plus récent (requis par pandas 3).
4. **Deploy**. Chaque `git push` sur `main` redéploie l'application.

Le bouton **Mettre à jour les données** fonctionne en ligne, mais le serveur repart des fichiers du dépôt
à chaque redémarrage. Pour rendre une mise à jour définitive : lancer l'import en local puis pousser
les fichiers `data/` sur GitHub.

## Fichiers

| Fichier | Contenu |
|---|---|
| `data/stations.csv` | 33 stations, saisie manuelle (séparateur `;`, listes séparées par `\|`) |
| `data/dvf_stations.csv` | Prix médians au m² par station et par année (généré) |
| `data/dvf_ventes.csv` | Ventes retenues, rattachées à une station (généré) |
| `scripts/import_dvf.py` | Import et traitement DVF |
| `app/scoring.py` | Notation des stations et simulateur financier |
| `app/app.py` | Interface Streamlit |

## Fiabilité des données

- **Prix au m²** : ventes réelles DVF.
- **À vérifier** (estimations saisies à la main) : rendement brut, semaines louables, temps de trajet,
  note de vie 4 saisons, part de DPE F/G, kilomètres de pistes.
- **Indice neige 2050** : formule provisoire basée sur l'altitude, à remplacer par les projections DRIAS.

## Prochaines étapes (phase 2)

DPE réels (API ADEME), risques (Géorisques), projections climatiques (DRIAS), analyse d'annonce.

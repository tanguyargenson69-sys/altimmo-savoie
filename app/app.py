"""Altimmo Savoie : où acheter un appartement au ski en Savoie.

Lancement : streamlit run app/app.py
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from scoring import CRITERES, DEPARTS, MIN_VENTES_DVF, PROFILS, load_maj, load_stations, load_ventes, scorer, simulation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_dvf  # noqa: E402

st.set_page_config(page_title="Altimmo Savoie", page_icon="🏔️", layout="wide")

LAKE, GOOD, MID, LOW = "#0f5c63", "#2f8a57", "#b98512", "#b5432e"


def eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def couleur(score: float) -> str:
    return GOOD if score >= 70 else MID if score >= 50 else LOW


def date_fr(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y à %H:%M")


@st.cache_data
def donnees():
    return load_stations(), load_ventes(), load_maj()


def mettre_a_jour():
    with st.status("Mise à jour des données DVF…", expanded=True) as statut:
        barre = st.progress(0.0, text="Téléchargement")
        try:
            maj = import_dvf.main(refresh=True, log=statut.write,
                                  progression=lambda f: barre.progress(f, text=f"Téléchargement : {f:.0%}"))
        except (Exception, SystemExit) as e:
            statut.update(label="La mise à jour a échoué", state="error")
            st.error(f"Les données précédentes sont conservées. Détail : {e}")
            return
        statut.update(label=f"Données mises à jour le {date_fr(maj['date'])}", state="complete", expanded=False)
    st.cache_data.clear()
    st.session_state["maj_ok"] = maj["date"]
    st.rerun()


stations, ventes, maj = donnees()
annees_dvf = sorted(int(c[5:]) for c in stations.columns if c.startswith("prix_") and c[5:].isdigit())
debut_dvf = annees_dvf[0] if annees_dvf else ""

# ---------- Panneau latéral : le projet ----------
with st.sidebar:
    st.header("Mon projet")
    profil = st.radio("Profil", list(PROFILS), index=1, horizontal=True, key="profil")
    if st.session_state.get("profil_prec") != profil:
        for k, v in PROFILS[profil].items():
            st.session_state[f"w_{k}"] = v
        st.session_state["profil_prec"] = profil
    budget = st.slider("Budget total (€)", 100_000, 1_500_000, 380_000, 10_000, format="%d €")
    surface_min = st.slider("Surface minimale (m²)", 18, 90, 35)
    depart = st.selectbox("Je pars de", list(DEPARTS))
    secteur = st.selectbox("Secteur", ["Toute la Savoie", *sorted(stations["vallee"].unique())])

    st.subheader("Importance des critères")
    st.caption("Le profil règle les curseurs. Ajustez-les à votre goût.")
    poids = {k: st.slider(nom, 0, 40, key=f"w_{k}") for k, nom in CRITERES.items()}

    st.divider()
    st.subheader("Données")
    if maj:
        st.markdown(f"**Dernière mise à jour :** {date_fr(maj['date'])}")
        st.caption(f"Ventes DVF {maj['annees'][0]}-{maj['annees'][-1]} · {maj['nb_ventes']:,} ventes retenues · "
                   f"vente la plus récente : {pd.to_datetime(maj['derniere_vente']):%d/%m/%Y}".replace(",", " "))
    else:
        st.caption("Aucune mise à jour enregistrée.")
    if st.button("Mettre à jour les données", icon="🔄", width="stretch",
                 help="Retélécharge les ventes DVF sur data.gouv.fr et recalcule les prix (1 à 3 minutes)."):
        mettre_a_jour()
    if st.session_state.pop("maj_ok", None):
        st.success("Données mises à jour.")

res = scorer(stations, poids, budget, surface_min, depart)
if secteur != "Toute la Savoie":
    res = res[res["vallee"] == secteur].reset_index(drop=True)

# ---------- En-tête ----------
st.title("Altimmo Savoie")
periode = f"{annees_dvf[0]}-{annees_dvf[-1]}" if annees_dvf else ""
st.caption(
    f"Prix au m² issus des ventes réelles DVF {periode} (seuil de fiabilité : {MIN_VENTES_DVF} ventes)"
    + (f", mis à jour le {date_fr(maj['date'])}" if maj else "") + ". "
    "Les autres indicateurs (rendement, accès, vie, DPE) sont des estimations saisies à la main, à vérifier."
)

c1, c2, c3 = st.columns(3)
dans_budget = res[res["dans_budget"]]
c1.metric("Stations dans le budget", f"{len(dans_budget)} / {len(res)}")
if len(dans_budget):
    top = dans_budget.iloc[0]
    c2.metric("Meilleur score dans le budget", top["nom"], f"{top['score']} / 100", delta_color="off")
    c3.metric("Surface accessible dans cette station", f"{top['m2_budget']:.0f} m²")

tab_classement, tab_fiche, tab_cmp, tab_sim = st.tabs(["Classement et carte", "Fiche station", "Comparateur", "Simulateur"])

# ---------- Classement et carte ----------
with tab_classement:
    col_carte, col_liste = st.columns([1.1, 1])
    with col_carte:
        carte = res.assign(
            statut=res["dans_budget"].map({True: "Dans le budget", False: "Hors budget"}),
            taille=res["score"].clip(lower=10),
        )
        fig = px.scatter_map(
            carte, lat="lat", lon="lon", color="score", size="taille", size_max=22,
            color_continuous_scale=[LOW, MID, GOOD], range_color=[30, 85],
            hover_name="nom", hover_data={"score": True, "prix_m2": ":.0f", "statut": True, "lat": False, "lon": False, "taille": False},
            zoom=8.3, center={"lat": 45.45, "lon": 6.6}, map_style="open-street-map", height=560,
        )
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), coloraxis_colorbar=dict(title="Score"))
        st.plotly_chart(fig, width="stretch")
    with col_liste:
        tableau = res[["nom", "score", "prix_m2", "prix_source", "m2_budget", "alt_station", "domaine", "dans_budget"]].copy()
        tableau.insert(0, "rang", range(1, len(tableau) + 1))
        st.dataframe(
            tableau, hide_index=True, height=560, width="stretch",
            column_config={
                "rang": st.column_config.NumberColumn("#", width="small"),
                "nom": "Station",
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "prix_m2": st.column_config.NumberColumn("€/m²", format="%d"),
                "prix_source": "Source prix",
                "m2_budget": st.column_config.NumberColumn("m² accessibles", format="%.0f"),
                "alt_station": st.column_config.NumberColumn("Altitude", format="%d m"),
                "domaine": "Domaine",
                "dans_budget": st.column_config.CheckboxColumn("Budget OK"),
            },
        )

# ---------- Fiche station ----------
with tab_fiche:
    nom = st.selectbox("Station", res["nom"], key="fiche_station")
    s = res[res["nom"] == nom].iloc[0]
    rang = int(res.index[res["nom"] == nom][0]) + 1

    h1, h2 = st.columns([3, 1])
    h1.subheader(s["nom"])
    h1.caption(f"{s['vallee']} · {s['domaine']} · {rang}ᵉ du classement")
    h2.markdown(f"<div style='text-align:right;font-size:44px;font-weight:800;color:{couleur(s['score'])}'>{s['score']}"
                f"<span style='font-size:16px;color:gray'> / 100</span></div>", unsafe_allow_html=True)

    k = st.columns(6)
    k[0].metric("Prix médian", f"{s['prix_m2']:,.0f} €/m²".replace(",", " "),
                f"{s['evol_pct']:+.0f} % depuis {debut_dvf}" if pd.notna(s.get("evol_pct")) else None)
    k[1].metric("Avec mon budget", f"{s['m2_budget']:.0f} m²")
    k[2].metric("Altitude", f"{s['alt_station']} → {s['alt_max']} m")
    k[3].metric("Domaine", f"{s['km_pistes']} km")
    k[4].metric("Rendement brut (estim.)", f"{s['rdt_brut']:.1f} %".replace(".", ","))
    k[5].metric("Trajet", f"{s['trajet_h']:.1f} h".replace(".", ","))
    if s["prix_source"] == "Estimation":
        st.warning(f"Seulement {int(s['nb_ventes'] or 0)} ventes DVF trouvées : le prix affiché est une estimation manuelle.")
    elif s.get("perimetre") == "commune":
        st.info("Peu de ventes près du centre de la station : le prix est calculé sur toute la commune.")

    g1, g2, g3 = st.columns([1, 1.3, 1])
    with g1:
        labels = list(CRITERES.values())
        vals = [s[f"note_{k}"] for k in CRITERES]
        radar = go.Figure(go.Scatterpolar(r=vals + vals[:1], theta=labels + labels[:1], fill="toself",
                                          line_color=LAKE, fillcolor="rgba(15,92,99,0.25)"))
        radar.update_layout(polar=dict(radialaxis=dict(range=[0, 100], showticklabels=False)),
                            showlegend=False, margin=dict(l=40, r=40, t=20, b=20), height=300)
        st.plotly_chart(radar, width="stretch")
    with g2:
        annees = [y for y in annees_dvf if pd.notna(s.get(f"prix_{y}"))]
        if annees:
            evol = pd.DataFrame({"Année": [str(y) for y in annees], "€/m²": [s[f"prix_{y}"] for y in annees]})
            fig = px.bar(evol, x="Année", y="€/m²", text_auto=",.0f", color_discrete_sequence=[LAKE], height=300,
                         title="Prix médian au m² par année (DVF)")
            fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, width="stretch")
    with g3:
        st.markdown("**Neige en 2050**")
        st.progress(s["neige_2050"] / 100, text=f"Indice de fiabilité : {s['neige_2050']} / 100")
        st.caption("Indice provisoire calculé à partir de l'altitude. À remplacer par les projections DRIAS.")
        st.markdown(f"**Risques naturels :** {s['risques'].replace('|', ', ')}")
        st.markdown(f"**Gare :** {s['gare']}")

    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown("**Forces**")
        st.markdown("\n".join(f"- {x}" for x in s["forces"]))
    with p2:
        st.markdown("**Faiblesses**")
        st.markdown("\n".join(f"- {x}" for x in s["faiblesses"]))
    with p3:
        st.markdown("**Points de vigilance**")
        st.error(f"{s['dpe_fg']} % des logements classés DPE F ou G (estimation). "
                 "Les G ne peuvent plus être loués depuis 2025, les F seront interdits en 2028.")
        if s["alt_station"] < 1500:
            st.warning("Station sous 1500 m : vérifier la part du domaine couverte par la neige de culture.")

    if not ventes.empty:
        st.markdown("**Dernières ventes d'appartements (DVF)**")
        dernieres = (ventes[ventes["station_id"] == s["id"]].sort_values("date_mutation", ascending=False).head(20)
                     [["date_mutation", "adresse_nom_voie", "surface_reelle_bati", "nombre_pieces_principales", "valeur_fonciere", "prix_m2"]])
        st.dataframe(dernieres, hide_index=True, width="stretch", column_config={
            "date_mutation": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            "adresse_nom_voie": "Voie",
            "surface_reelle_bati": st.column_config.NumberColumn("Surface", format="%d m²"),
            "nombre_pieces_principales": st.column_config.NumberColumn("Pièces", format="%d"),
            "valeur_fonciere": st.column_config.NumberColumn("Prix", format="%d €"),
            "prix_m2": st.column_config.NumberColumn("€/m²", format="%d"),
        })

# ---------- Comparateur ----------
with tab_cmp:
    choix = st.multiselect("Stations à comparer (4 au maximum)", res["nom"], default=list(res["nom"][:3]), max_selections=4)
    if choix:
        sel = res[res["nom"].isin(choix)].set_index("nom").loc[choix]
        lignes = {
            "Score global": ("score", "max", "{:.0f}"),
            "Prix au m²": ("prix_m2", "min", "{:,.0f} €"),
            "Surface avec mon budget": ("m2_budget", "max", "{:.0f} m²"),
            "Altitude station": ("alt_station", "max", "{:.0f} m"),
            "Kilomètres de pistes": ("km_pistes", "max", "{:.0f} km"),
            "Rendement brut (estim.)": ("rdt_brut", "max", "{:.1f} %"),
            f"Évolution des prix depuis {debut_dvf}": ("evol_pct", "max", "{:+.0f} %"),
            "Trajet": ("trajet_h", "min", "{:.1f} h"),
            "Logements DPE F ou G (estim.)": ("dpe_fg", "min", "{:.0f} %"),
            "Indice neige 2050": ("neige_2050", "max", "{:.0f}"),
        }
        # Des fichiers DVF d'un ancien format peuvent ne pas avoir toutes les colonnes
        lignes = {lab: v for lab, v in lignes.items() if v[0] in sel.columns}
        table = pd.DataFrame({lab: [fmt.format(v).replace(",", " ") if pd.notna(v) else "–" for v in sel[col]]
                              for lab, (col, _, fmt) in lignes.items()}, index=choix).T

        def surligne(row):
            col, sens, _ = lignes[row.name]
            vals = sel[col]
            best = vals.max() if sens == "max" else vals.min()
            return [f"color:{GOOD};font-weight:600" if v == best else "" for v in vals]

        st.dataframe(table.style.apply(surligne, axis=1), width="stretch")

# ---------- Simulateur ----------
with tab_sim:
    nom_sim = st.selectbox("Station", res["nom"], key="sim_station")
    s = res[res["nom"] == nom_sim].iloc[0]
    e1, e2 = st.columns(2)
    with e1:
        a, b = st.columns(2)
        surf = a.number_input("Surface (m²)", 10, 200, surface_min)
        prix = b.number_input("Prix du bien (€)", 20_000, 3_000_000, int(round(s["prix_m2"] * surf, -3)), 1000)
        apport = a.number_input("Apport (€)", 0, 3_000_000, 80_000, 1000)
        taux = b.number_input("Taux du prêt (%)", 0.0, 10.0, 3.4, 0.05)
        duree = a.number_input("Durée (ans)", 5, 25, 20)
        perso = b.number_input("Semaines d'usage perso", 0, 20, 3)
        charges = a.number_input("Charges de copro (€/an)", 0, 50_000, int(round(surf * (62 if s["dpe_fg"] > 30 else 48), -2)), 100)
        tf = b.number_input("Taxe foncière (€/an)", 0, 20_000, int(round(surf * 14, -1)), 50)
        tmi = a.selectbox("Tranche d'imposition", [0.11, 0.30, 0.41, 0.45], index=1, format_func=lambda x: f"{x:.0%}")
        classe = b.selectbox("Meublé de tourisme", ["Non classé", "Classé"]) == "Classé"
    r = simulation(prix, apport, taux, duree, s["rdt_brut"], s["semaines"], perso, charges, tf, tmi, classe)
    with e2:
        lignes_sim = [
            ("Frais de notaire (8 %)", eur(r["notaire"])),
            ("Montant emprunté", eur(r["emprunt"])),
            ("Mensualité du prêt", eur(r["mensualite"])),
            (f"Loyers bruts ({r['semaines_louees']} semaines louées)", eur(r["loyers"]) + " / an"),
            ("Conciergerie et ménage (22 %)", "− " + eur(r["gestion"])),
            ("Charges et taxe foncière", "− " + eur(charges + tf)),
            ("Rendement net", f"{r['rendement_net']:.2f} %".replace(".", ",")),
        ]
        st.table(pd.DataFrame(lignes_sim, columns=["Poste", "Montant"]).set_index("Poste"))
        signe = "+" if r["cashflow"] >= 0 else "−"
        st.metric("Effort d'épargne mensuel (avant impôt)", f"{signe} {eur(abs(r['cashflow']))} / mois")

        st.markdown("**Fiscalité la première année (LMNP)**")
        micro = eur(r["impot_micro"]) + " / an" if r["impot_micro"] is not None else "non applicable (plafond dépassé)"
        st.markdown(f"- Micro-BIC (abattement {r['abattement']:.0%}) : **{micro}**\n"
                    f"- Régime réel (charges, intérêts, amortissement) : **{eur(r['impot_reel'])} / an**")
        if r["deficit_reportable"] > 0:
            st.caption(f"Au réel, le déficit de {eur(r['deficit_reportable'])} est reportable sur les années suivantes.")
        st.caption("Estimation simplifiée, à valider avec un expert-comptable.")

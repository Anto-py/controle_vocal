"""Critère de l'étape 13 : les routes répondent, un PUT fautif ne touche à rien.

Les tests appellent `router` directement : aucun port ouvert, aucun navigateur.
"""

import json
from pathlib import Path

import pytest

from controle_vocal import profils
from controle_vocal.reglages import Reglages, router

EN_TETE = "application,bundle_id,commande,touches,phrases,actif\n"
CANVA = (
    EN_TETE
    + "Canva,com.canva.CanvaDesktop,reveil,@reveil,higgins,oui\n"
    + "Canva,com.canva.CanvaDesktop,suivante,droite,suivante|avance,oui\n"
    + "Canva,com.canva.CanvaDesktop,debut,,début,non\n"
)


def touche_connue(combinaison: str) -> None:
    if combinaison not in {"droite", "gauche", "echap", "b"}:
        raise ValueError(f"touche inconnue : « {combinaison} »")


@pytest.fixture
def dossier(tmp_path: Path) -> Path:
    (tmp_path / "canva.csv").write_text(CANVA, encoding="utf-8")
    (tmp_path / "defaut.csv").write_text(
        EN_TETE + "Défaut,,suivante,droite,avance,oui\n", encoding="utf-8"
    )
    (tmp_path / "_gabarit.csv").write_text(EN_TETE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def reglages(dossier: Path) -> Reglages:
    return Reglages(dossier, verifier_touche=touche_connue)


def charge(reponse) -> dict:  # noqa: ANN001
    return json.loads(reponse.corps.decode("utf-8"))


# --- Lecture ---------------------------------------------------------------


def test_liste_des_profils_exclut_le_gabarit(reglages: Reglages) -> None:
    reponse = router(reglages, "GET", "/api/profils")
    assert reponse.code == 200
    noms = [p["nom"] for p in charge(reponse)["profils"]]
    assert noms == ["canva", "defaut"]


def test_liste_compte_les_lignes_actives(reglages: Reglages) -> None:
    canva = charge(router(reglages, "GET", "/api/profils"))["profils"][0]
    assert canva["application"] == "Canva"
    assert canva["bundle_id"] == "com.canva.CanvaDesktop"
    assert canva["commandes"] == 2  # `debut` est inactive
    assert canva["total"] == 3


def test_lecture_rend_les_lignes_brutes(reglages: Reglages) -> None:
    lignes = charge(router(reglages, "GET", "/api/profils/canva"))["lignes"]
    assert lignes[0]["touches"] == "@reveil"
    assert lignes[2]["phrases"] == "début"


def test_profil_inconnu_rend_404(reglages: Reglages) -> None:
    assert router(reglages, "GET", "/api/profils/absent").code == 404


def test_export_rend_le_csv_tel_quel(reglages: Reglages) -> None:
    reponse = router(reglages, "GET", "/api/profils/canva/export")
    assert reponse.corps.decode("utf-8") == CANVA


def test_gabarit_est_servi(reglages: Reglages) -> None:
    reponse = router(reglages, "GET", "/api/gabarit")
    assert reponse.corps.decode("utf-8") == EN_TETE


def test_route_inconnue_rend_404(reglages: Reglages) -> None:
    assert router(reglages, "GET", "/api/inexistant").code == 404


# --- Traversée de répertoire ----------------------------------------------


@pytest.mark.parametrize(
    "nom",
    ["../secret", "..%2Fsecret", "canva.csv", "Canva", "a/b", "", "profil-1"],
)
def test_nom_de_profil_hors_convention_est_refuse(reglages: Reglages, nom: str) -> None:
    reponse = router(reglages, "GET", f"/api/profils/{nom}")
    assert reponse.code in (400, 404)


def test_ecriture_hors_du_dossier_est_refusee(reglages: Reglages, tmp_path: Path) -> None:
    voisin = tmp_path.parent / "voisin.csv"
    corps = json.dumps({"lignes": []}).encode("utf-8")
    reponse = router(reglages, "PUT", "/api/profils/..%2Fvoisin", corps)
    assert reponse.code == 400
    assert not voisin.exists()


def test_statique_ne_sort_pas_de_son_dossier(reglages: Reglages) -> None:
    assert router(reglages, "GET", "/../../SPECS.md").code == 404


# --- Écriture --------------------------------------------------------------


def ligne(commande: str, touches: str, phrases: str, actif: str = "oui") -> dict:
    return {
        "application": "Canva",
        "bundle_id": "com.canva.CanvaDesktop",
        "commande": commande,
        "touches": touches,
        "phrases": phrases,
        "actif": actif,
    }


def test_enregistrement_valide_ecrit_le_fichier(reglages: Reglages, dossier: Path) -> None:
    lignes = [
        ligne("reveil", "@reveil", "higgins"),
        ligne("suivante", "droite", "suivante|avance|page suivante"),
    ]
    reponse = router(
        reglages, "PUT", "/api/profils/canva", json.dumps({"lignes": lignes}).encode()
    )
    assert reponse.code == 200
    assert "page suivante" in (dossier / "canva.csv").read_text(encoding="utf-8")


def test_enregistrement_fautif_ne_touche_pas_le_fichier(
    reglages: Reglages, dossier: Path
) -> None:
    lignes = [ligne("suivante", "drooite", "avance")]
    reponse = router(
        reglages, "PUT", "/api/profils/canva", json.dumps({"lignes": lignes}).encode()
    )
    assert reponse.code == 422
    assert charge(reponse)["refus"][0]["colonne"] == "touches"
    assert (dossier / "canva.csv").read_text(encoding="utf-8") == CANVA


def test_corps_illisible_rend_400(reglages: Reglages) -> None:
    assert router(reglages, "PUT", "/api/profils/canva", b"{pas du json").code == 400


def test_corps_sans_lignes_rend_400(reglages: Reglages) -> None:
    corps = json.dumps({"autre": []}).encode()
    assert router(reglages, "PUT", "/api/profils/canva", corps).code == 400


def test_enregistre_puis_se_charge(reglages: Reglages, dossier: Path) -> None:
    """La garantie du jalon : ce que l'interface accepte, le cœur le charge."""
    lignes = [
        ligne("reveil", "@reveil", "higgins"),
        ligne("suivante", "droite", "avance"),
        ligne("sortir", "echap", "sortir"),
    ]
    router(reglages, "PUT", "/api/profils/canva", json.dumps({"lignes": lignes}).encode())
    profil = profils.charger(dossier / "canva.csv")
    assert profil.resoudre("avance").touches == "droite"


# --- Import ----------------------------------------------------------------


def test_import_remplace_le_profil(reglages: Reglages, dossier: Path) -> None:
    csv_importe = EN_TETE + "Keynote,com.apple.iWork.Keynote,suivante,droite,avance,oui\n"
    reponse = router(
        reglages, "POST", "/api/profils/keynote/import", csv_importe.encode("utf-8")
    )
    assert reponse.code == 200
    assert (dossier / "keynote.csv").exists()


def test_import_sans_les_colonnes_est_refuse(reglages: Reglages, dossier: Path) -> None:
    reponse = router(
        reglages, "POST", "/api/profils/keynote/import", b"a,b\n1,2\n"
    )
    assert reponse.code == 422
    assert "gabarit" in charge(reponse)["refus"][0]["message"]
    assert not (dossier / "keynote.csv").exists()


def test_import_fautif_ne_cree_rien(reglages: Reglages, dossier: Path) -> None:
    csv_importe = (
        EN_TETE
        + "Keynote,,suivante,droite,avance,oui\n"
        + "Keynote,,precedente,gauche,avance,oui\n"
    )
    reponse = router(
        reglages, "POST", "/api/profils/keynote/import", csv_importe.encode("utf-8")
    )
    assert reponse.code == 422
    assert not (dossier / "keynote.csv").exists()


# --- Divers ----------------------------------------------------------------


def test_methode_refusee_sur_le_statique(reglages: Reglages) -> None:
    assert router(reglages, "PUT", "/index.html").code == 405


def test_touches_connues_sont_servies(reglages: Reglages) -> None:
    reponse = router(reglages, "GET", "/api/touches")
    assert reponse.code == 200
    assert "touches" in charge(reponse)


# --- Marche et arrêt de la télécommande ------------------------------------


@pytest.fixture
def avec_moteur(dossier: Path) -> Reglages:
    """Un moteur qui lance un faux outil : ces tests éprouvent les routes, pas la
    boucle d'écoute, et n'ouvrent aucun micro."""
    import sys

    from controle_vocal.reglages.moteur import Moteur

    script = "import time; print('en écoute', flush=True); time.sleep(60)"
    moteur = Moteur(dossier.parent, fabriquer_argv=lambda p, q: [sys.executable, "-c", script])
    reglages = Reglages(dossier, verifier_touche=touche_connue, moteur=moteur)
    yield reglages
    moteur.fermer()


def test_sans_moteur_les_routes_disent_qu_elles_ne_conduisent_rien(
    reglages: Reglages,
) -> None:
    assert router(reglages, "GET", "/api/moteur").code == 501


def test_etat_initial_est_arrete(avec_moteur: Reglages) -> None:
    reponse = router(avec_moteur, "GET", "/api/moteur")
    assert reponse.code == 200
    assert charge(reponse)["actif"] is False


def test_demarrer_puis_arreter(avec_moteur: Reglages) -> None:
    demarrage = router(avec_moteur, "POST", "/api/moteur/demarrer", b"{}")
    assert demarrage.code == 200
    assert charge(demarrage)["actif"] is True

    arret = router(avec_moteur, "POST", "/api/moteur/arreter")
    assert arret.code == 200
    assert charge(arret)["actif"] is False


def test_demarrer_deux_fois_rend_409(avec_moteur: Reglages) -> None:
    router(avec_moteur, "POST", "/api/moteur/demarrer", b"{}")
    assert router(avec_moteur, "POST", "/api/moteur/demarrer", b"{}").code == 409


def test_arreter_ce_qui_dort_rend_409(avec_moteur: Reglages) -> None:
    assert router(avec_moteur, "POST", "/api/moteur/arreter").code == 409


def test_les_options_remontent_dans_l_etat(avec_moteur: Reglages) -> None:
    corps = json.dumps({"profil": "canva", "pastille": True}).encode()
    etat = charge(router(avec_moteur, "POST", "/api/moteur/demarrer", corps))
    assert etat["options"] == {"profil": "canva", "pastille": True}


def test_profil_inconnu_ne_lance_rien(avec_moteur: Reglages) -> None:
    corps = json.dumps({"profil": "absent"}).encode()
    assert router(avec_moteur, "POST", "/api/moteur/demarrer", corps).code == 404
    assert charge(router(avec_moteur, "GET", "/api/moteur"))["actif"] is False


def test_profil_hors_convention_ne_lance_rien(avec_moteur: Reglages) -> None:
    """Le nom finit en argument d'un processus : il passe le même contrôle qu'à
    l'édition."""
    corps = json.dumps({"profil": "../../etc/passwd"}).encode()
    assert router(avec_moteur, "POST", "/api/moteur/demarrer", corps).code == 400
    assert charge(router(avec_moteur, "GET", "/api/moteur"))["actif"] is False


def test_route_moteur_inconnue_rend_404(avec_moteur: Reglages) -> None:
    assert router(avec_moteur, "POST", "/api/moteur/redemarrer", b"{}").code == 404


# --- Autorisation macOS ----------------------------------------------------


def test_sans_macos_l_autorisation_n_est_pas_consultable(reglages: Reglages) -> None:
    assert router(reglages, "GET", "/api/accessibilite").code == 501


def test_etat_de_l_autorisation_est_servi(dossier: Path) -> None:
    reglages = Reglages(dossier, lire_accessibilite=lambda: True)
    assert charge(router(reglages, "GET", "/api/accessibilite"))["accordee"] is True


def test_demander_l_autorisation_passe_par_le_systeme(dossier: Path) -> None:
    """Lire l'état n'inscrit rien dans le panneau des Réglages système ; seule la
    demande le fait. Les deux routes ne sont donc pas interchangeables."""
    appels = []
    reglages = Reglages(
        dossier,
        lire_accessibilite=lambda: False,
        demander_accessibilite=lambda: appels.append(1) or False,
    )
    assert router(reglages, "POST", "/api/accessibilite/demander").code == 200
    assert appels == [1]


def test_demande_refusee_si_seule_la_lecture_est_branchee(dossier: Path) -> None:
    reglages = Reglages(dossier, lire_accessibilite=lambda: False)
    assert router(reglages, "POST", "/api/accessibilite/demander").code == 501


def test_fermeture_refusee_si_l_interface_ne_sait_pas_se_fermer(
    reglages: Reglages,
) -> None:
    assert router(reglages, "POST", "/api/quitter").code == 501


def test_fermeture_appelle_l_arret_du_serveur(dossier: Path) -> None:
    """Lancée depuis une application du Dock, l'interface n'a pas de terminal où
    faire Ctrl+C."""
    appels = []
    reglages = Reglages(dossier, arreter_serveur=lambda: appels.append(1))
    assert router(reglages, "POST", "/api/quitter").code == 200
    assert appels == [1]


def test_profil_illisible_apparait_dans_la_liste(reglages: Reglages, dossier: Path) -> None:
    """Un CSV cassé à la main ne doit pas faire disparaître les autres."""
    (dossier / "casse.csv").write_text("pas,les,bonnes,colonnes\n", encoding="utf-8")
    profils_listes = charge(router(reglages, "GET", "/api/profils"))["profils"]
    casse = next(p for p in profils_listes if p["nom"] == "casse")
    assert "colonnes absentes" in casse["erreur"]
    assert len(profils_listes) == 3

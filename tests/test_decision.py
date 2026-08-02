"""Critères de l'étape 6 : le motif protège, le seuil trie, l'état tient.

Les cas limites suivent le tableau de `docs/PLAN.md`. Les énoncés sont fabriqués à
la main : ce qui est éprouvé ici est la décision, pas la reconnaissance.
"""

from pathlib import Path

import pytest

from controle_vocal import profils
from controle_vocal.application import ApplicationActive
from controle_vocal.decision import (
    Decideur,
    ErreurDecision,
    Etat,
    reconnaitre_motif,
)
from controle_vocal.reconnaissance import Enonce

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"


def enonce(texte: str, certitude: float = 1.0) -> Enonce:
    mots = tuple((mot, certitude) for mot in texte.split())
    return Enonce(texte=texte, certitude=certitude, mots=mots)


@pytest.fixture
def jeu() -> dict[str, profils.Profil]:
    return profils.charger_tous(DOSSIER_PROFILS)


@pytest.fixture
def canva(jeu: dict[str, profils.Profil]) -> profils.Profil:
    return jeu["canva"]


def decideur_sur(
    jeu: dict[str, profils.Profil], bundle: str = "com.canva.CanvaDesktop", **options
) -> Decideur:
    """Décideur dont l'application au premier plan est figée, sans toucher aux fenêtres."""
    return Decideur(
        jeu,
        lire_application=lambda: ApplicationActive(bundle_id=bundle, nom="essai"),
        **options,
    )


# --- Le motif, seule barrière réelle contre les faux déclenchements ---------


def test_reveil_puis_commande_est_reconnu(canva: profils.Profil) -> None:
    motif = reconnaitre_motif("higgins suivante", canva)
    assert motif.commande is not None and motif.commande.nom == "suivante"


def test_commande_sans_reveil_ne_declenche_rien(canva: profils.Profil) -> None:
    motif = reconnaitre_motif("suivante", canva)
    assert motif.reveil is False and motif.commande is None


def test_reveil_seul_ne_declenche_rien(canva: profils.Profil) -> None:
    motif = reconnaitre_motif("higgins", canva)
    assert motif.reveil is True and motif.commande is None


def test_rabattement_de_la_grammaire_ne_declenche_rien(canva: profils.Profil) -> None:
    """Le cas mesuré le 2026-08-02 : une phrase de cours ressort en commandes
    enchaînées, avec des scores élevés. Sans mot de réveil, rien ne part."""
    assert reconnaitre_motif("pause reviens avance", canva).commande is None


def test_bruit_apres_la_commande_annule_tout(canva: profils.Profil) -> None:
    assert reconnaitre_motif("higgins suivante avance", canva).commande is None


def test_parasite_intercale_rejete_sans_tolerance(canva: profils.Profil) -> None:
    """« Higgins, écran noir » est ressorti en « higgins reprends noir »."""
    assert reconnaitre_motif("higgins reprends noir", canva).commande is None


def test_parasite_intercale_admis_avec_tolerance(canva: profils.Profil) -> None:
    motif = reconnaitre_motif("higgins reprends noir", canva, tolerance=1)
    assert motif.commande is not None and motif.commande.nom == "ecran_noir"


def test_le_dernier_reveil_gagne(canva: profils.Profil) -> None:
    motif = reconnaitre_motif("higgins avance higgins suivante", canva)
    assert motif.commande is not None and motif.commande.nom == "suivante"


def test_commande_desactivee_ne_resout_pas(canva: profils.Profil) -> None:
    """`debut` n'a pas de touche vérifiée : la ligne reste hors circuit."""
    assert reconnaitre_motif("higgins début", canva).commande is None


# --- Le seuil, qui ne trie que l'hésitation ---------------------------------


def test_certitude_basse_donne_incompris(jeu: dict[str, profils.Profil]) -> None:
    decideur = decideur_sur(jeu, seuil=0.9)
    decision = decideur.traiter(enonce("higgins suivante", certitude=0.4))
    assert decision.etat is Etat.INCOMPRIS
    assert decision.a_agir is False


def test_certitude_suffisante_execute(jeu: dict[str, profils.Profil]) -> None:
    decision = decideur_sur(jeu, seuil=0.9).traiter(enonce("higgins suivante", 0.95))
    assert decision.etat is Etat.EXECUTE
    assert decision.a_agir is True
    assert decision.touches == "droite"


def test_un_seul_mot_faible_suffit_a_rejeter(jeu: dict[str, profils.Profil]) -> None:
    """Le cas mesuré à la voix : « higgins pause » fabriqué depuis une phrase de
    cours passait à 0,82 de moyenne, un mot sûr rachetant un mot douteux."""
    fabrique = Enonce(
        texte="higgins pause",
        certitude=0.82,
        mots=(("higgins", 1.0), ("pause", 0.64)),
    )
    decision = decideur_sur(jeu, seuil=0.9).traiter(fabrique)
    assert decision.etat is Etat.INCOMPRIS
    assert decision.a_agir is False


def test_enonce_sans_detail_par_mot_retombe_sur_la_moyenne() -> None:
    """Les énoncés fabriqués à la main (option `--texte`) n'ont pas de détail."""
    assert Enonce(texte="higgins suivante", certitude=0.5, mots=()).plancher == 0.5


# --- Le profil actif --------------------------------------------------------


def test_le_profil_suit_l_application_au_premier_plan(
    jeu: dict[str, profils.Profil],
) -> None:
    assert decideur_sur(jeu).rafraichir_profil().nom == "canva"
    assert decideur_sur(jeu, bundle="com.inconnue.App").rafraichir_profil().nom == "defaut"


def test_le_profil_epingle_ignore_le_premier_plan(jeu: dict[str, profils.Profil]) -> None:
    decideur = decideur_sur(jeu, bundle="com.inconnue.App", epingle="canva")
    assert decideur.rafraichir_profil().nom == "canva"


def test_profil_epingle_introuvable_est_refuse(jeu: dict[str, profils.Profil]) -> None:
    with pytest.raises(ErreurDecision):
        decideur_sur(jeu, epingle="powerpoint")


def test_jeu_sans_repli_est_refuse(jeu: dict[str, profils.Profil]) -> None:
    with pytest.raises(ErreurDecision):
        decideur_sur({"canva": jeu["canva"]})


def test_sur_application_inconnue_la_navigation_reste(
    jeu: dict[str, profils.Profil],
) -> None:
    decideur = decideur_sur(jeu, bundle="com.inconnue.App")
    decision = decideur.traiter(enonce("higgins suivante"))
    assert decision.etat is Etat.EXECUTE and decision.touches == "droite"
    # Le profil de repli n'a pas les commandes propres à Canva.
    assert decideur.traiter(enonce("higgins noir")).etat is Etat.ENTENDU


# --- Les actions internes ---------------------------------------------------


def test_pause_puis_reprise(jeu: dict[str, profils.Profil]) -> None:
    decideur = decideur_sur(jeu)
    pause = decideur.traiter(enonce("higgins pause"))
    assert pause.etat is Etat.EXECUTE and pause.a_agir is False and decideur.en_pause

    ignoree = decideur.traiter(enonce("higgins suivante"))
    assert ignoree.etat is Etat.IGNORE and ignoree.a_agir is False

    reprise = decideur.traiter(enonce("higgins reprends"))
    assert reprise.etat is Etat.EXECUTE and decideur.en_pause is False
    assert decideur.traiter(enonce("higgins suivante")).a_agir is True


def test_extinction_demande_l_arret(jeu: dict[str, profils.Profil]) -> None:
    decideur = decideur_sur(jeu)
    decision = decideur.traiter(enonce("higgins extinction"))
    assert decision.etat is Etat.EXECUTE and decideur.arret_demande is True
    assert decision.a_agir is False


def test_rien_de_reconnaissable_est_ignore(jeu: dict[str, profils.Profil]) -> None:
    decideur = decideur_sur(jeu)
    assert decideur.traiter(None).etat is Etat.IGNORE
    assert decideur.traiter(enonce("[unk]")).etat is Etat.IGNORE

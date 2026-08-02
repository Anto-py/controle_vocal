"""Critère de l'étape 12 : ce que la validation accepte, le chargement le charge.

La garantie tient en une phrase : un profil enregistré par l'interface de réglages
ne doit jamais faire échouer un lancement devant le public.
"""

from pathlib import Path

import pytest

from controle_vocal import actions, profils, tableaux

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"

EN_TETE = "application,bundle_id,commande,touches,phrases,actif\n"


def ligne(
    commande: str,
    touches: str = "droite",
    phrases: str = "",
    actif: str = "oui",
    application: str = "Test",
    bundle_id: str = "",
) -> dict[str, str]:
    return {
        "application": application,
        "bundle_id": bundle_id,
        "commande": commande,
        "touches": touches,
        "phrases": phrases,
        "actif": actif,
    }


def touche_connue(combinaison: str) -> None:
    """Tient lieu de `clavier.analyser` sans dépendre de macOS dans ce test."""
    connues = {"droite", "gauche", "echap", "b", "cmd+alt+p"}
    if combinaison not in connues:
        raise ValueError(f"touche inconnue : « {combinaison} »")


# --- Lecture brute ---------------------------------------------------------


def test_lire_lignes_rend_le_fichier_tel_quel() -> None:
    lignes = profils.lire_lignes(DOSSIER_PROFILS / "canva.csv")
    # `charger` normaliserait « présentation » et rattacherait les actions
    # communes ; ici le fichier parle pour lui-même.
    presentation = next(l for l in lignes if l["commande"] == "presentation")
    assert presentation["phrases"] == "présentation|présente|démarre"


def test_un_profil_ne_porte_plus_aucune_action_interne() -> None:
    """Elles se règlent pour tout l'outil : un profil qui en garderait une aurait
    une ligne sans effet, découverte au pire moment."""
    for nom in ("canva.csv", "defaut.csv"):
        lignes = profils.lire_lignes(DOSSIER_PROFILS / nom)
        assert [l for l in lignes if l["touches"].startswith("@")] == []


def test_lire_lignes_refuse_un_fichier_sans_les_colonnes(tmp_path: Path) -> None:
    fichier = tmp_path / "tronque.csv"
    fichier.write_text("application,commande\nTest,suivante\n", encoding="utf-8")
    with pytest.raises(profils.ErreurProfil, match="colonnes absentes"):
        profils.lire_lignes(fichier)


# --- Aller-retour ----------------------------------------------------------


def test_aller_retour_sans_modification_rend_le_meme_fichier(tmp_path: Path) -> None:
    origine = (DOSSIER_PROFILS / "canva.csv").read_text(encoding="utf-8")
    copie = tmp_path / "canva.csv"
    copie.write_text(origine, encoding="utf-8")

    profils.ecrire(copie, profils.lire_lignes(copie))

    assert copie.read_text(encoding="utf-8") == origine


def test_ecriture_ne_laisse_aucun_fichier_provisoire(tmp_path: Path) -> None:
    fichier = tmp_path / "profil.csv"
    profils.ecrire(fichier, [ligne("suivante", phrases="avance")])
    assert [c.name for c in tmp_path.iterdir()] == ["profil.csv"]


def test_ecriture_interrompue_laisse_le_fichier_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L'échec est provoqué au renommage, après que le temporaire existe : c'est le
    seul moment où il y a quelque chose à nettoyer."""
    fichier = tmp_path / "profil.csv"
    fichier.write_text(EN_TETE + "Test,,suivante,droite,avance,oui\n", encoding="utf-8")
    origine = fichier.read_text(encoding="utf-8")

    def replace_qui_echoue(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr(tableaux.os, "replace", replace_qui_echoue)
    with pytest.raises(OSError, match="disque plein"):
        profils.ecrire(fichier, [ligne("autre", phrases="autre")])

    assert fichier.read_text(encoding="utf-8") == origine
    assert [c.name for c in tmp_path.iterdir()] == ["profil.csv"]


# --- Les quatre refus ------------------------------------------------------


def test_profil_de_reference_est_valide() -> None:
    lignes = profils.lire_lignes(DOSSIER_PROFILS / "canva.csv")
    assert profils.valider(lignes, verifier_touche=touche_connue) == []


def test_refus_colonne_absente() -> None:
    [refus] = profils.valider([{"commande": "suivante"}])
    assert refus.ligne == 2
    assert "colonnes absentes" in refus.message


def test_refus_touche_inconnue() -> None:
    [refus] = profils.valider(
        [ligne("suivante", touches="drooite", phrases="avance")],
        verifier_touche=touche_connue,
    )
    assert refus.colonne == "touches"
    assert "drooite" in refus.message


def test_touche_inconnue_ignoree_sans_verificateur() -> None:
    """Le module reste indépendant de macOS : sans vérificateur, pas de contrôle."""
    assert profils.valider([ligne("suivante", touches="drooite")]) == []


def test_touche_inconnue_toleree_sur_une_ligne_inactive() -> None:
    """`debut` et `fin` attendent leur raccourci sans bloquer l'enregistrement."""
    lignes = [ligne("debut", touches="", phrases="début", actif="non")]
    assert profils.valider(lignes, verifier_touche=touche_connue) == []


def test_refus_nom_de_commande_en_double() -> None:
    [refus] = profils.valider(
        [ligne("suivante", phrases="avance"), ligne("suivante", phrases="suite")]
    )
    assert refus.ligne == 3
    assert refus.colonne == "commande"


def test_refus_ligne_sans_nom() -> None:
    [refus] = profils.valider([ligne("", phrases="avance")])
    assert refus.colonne == "commande"


def test_refus_phrase_partagee_par_deux_commandes() -> None:
    [refus] = profils.valider(
        [
            ligne("suivante", touches="droite", phrases="avance"),
            ligne("precedente", touches="gauche", phrases="avance"),
        ]
    )
    assert refus.ligne == 3
    assert refus.colonne == "phrases"
    assert "imprévisible" in refus.message


def test_phrase_partagee_avec_une_ligne_inactive_est_admise() -> None:
    """Une ligne désactivée ne prend la parole nulle part."""
    lignes = [
        ligne("suivante", phrases="avance"),
        ligne("essai", touches="gauche", phrases="avance", actif="non"),
    ]
    assert profils.valider(lignes) == []


def test_phrase_repetee_dans_une_meme_ligne_est_admise() -> None:
    """`charger` la dédoublonne, la validation ne peut pas être plus stricte que lui."""
    assert profils.valider([ligne("suivante", phrases="avance|avance")]) == []


def test_refus_action_interne_dans_un_profil() -> None:
    """Elles se règlent pour tout l'outil : gardée ici, la ligne resterait sans
    effet, et le chargement la refuse aussi."""
    refus = profils.valider([ligne("pause", touches="@pause", phrases="pause")])
    [sur_la_touche] = [r for r in refus if r.colonne == "touches"]
    assert "mots de l'outil" in sur_la_touche.message


def test_une_commande_ne_peut_pas_reprendre_une_formulation_d_action() -> None:
    """`charger` refuse qu'une commande porte la phrase du réveil ou de la pause :
    la validation voit les mêmes formulations réservées."""
    [refus] = profils.valider([ligne("reveiller", phrases="higgins")])
    assert refus.ligne == 2
    assert refus.colonne == "phrases"
    assert "@reveil" in refus.message


def test_les_formulations_reservees_suivent_le_fichier_d_actions() -> None:
    """Le mot de réveil changé, c'est l'ancien qui redevient libre."""
    jeu = actions.charger()
    assert profils.valider(
        [ligne("suivante", phrases="higgins")],
        phrases_reservees={"jarvis": actions.ACTION_REVEIL},
    ) == []
    assert "higgins" in jeu.phrases_prises()


# --- La garantie -----------------------------------------------------------


@pytest.mark.parametrize(
    "lignes",
    [
        pytest.param([ligne("suivante", phrases="avance|suite")], id="simple"),
        pytest.param(
            [
                ligne("suivante", phrases="avance"),
                ligne("debut", touches="", phrases="début", actif="non"),
                ligne("noir", touches="b", phrases="noir|masque"),
            ],
            id="complet",
        ),
    ],
)
def test_ce_que_la_validation_accepte_se_charge(
    tmp_path: Path, lignes: list[dict[str, str]]
) -> None:
    assert profils.valider(lignes, verifier_touche=touche_connue) == []
    fichier = tmp_path / "accepte.csv"
    profils.ecrire(fichier, lignes)
    profils.charger(fichier)  # ne lève pas


def test_ce_que_le_chargement_refuse_est_refuse_ici(tmp_path: Path) -> None:
    fautif = [
        ligne("suivante", touches="droite", phrases="avance"),
        ligne("precedente", touches="gauche", phrases="avance"),
    ]
    fichier = tmp_path / "fautif.csv"
    profils.ecrire(fichier, fautif)
    with pytest.raises(profils.ErreurProfil):
        profils.charger(fichier)
    assert profils.valider(fautif) != []

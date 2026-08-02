"""Les mots de l'outil : réveil, pause, reprise, extinction.

Ils valent pour tous les profils. Ce qui se joue ici tient en trois garanties :
un mot de réveil changé est réellement entendu, un profil ne peut plus les
redéfinir dans son coin, et un dossier d'avant la séparation se rattrape tout
seul au premier lancement.
"""

from pathlib import Path

import pytest

from controle_vocal import actions, profils

EN_TETE = "application,bundle_id,commande,touches,phrases,actif\n"

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"


def ligne(action: str, phrases: str, actif: str = "oui") -> dict[str, str]:
    return {"action": action, "phrases": phrases, "actif": actif}


def ecrire_actions(dossier: Path, lignes: list[dict[str, str]]) -> Path:
    chemin = actions.chemin(dossier)
    actions.ecrire(chemin, lignes)
    return chemin


# --- Le jeu et ses valeurs d'origine ---------------------------------------


def test_sans_fichier_les_valeurs_d_origine() -> None:
    jeu = actions.charger()
    assert jeu.mots_reveil == ("higgins",)
    assert {a.nom for a in jeu.utilisables} == {"@pause", "@reprise", "@quitter"}


def test_le_mot_de_reveil_n_est_pas_une_commande() -> None:
    """Il précède les commandes, il n'en est pas une : il ne doit jamais se
    résoudre tout seul, ni entrer dans la grammaire sans une commande derrière."""
    assert actions.ACTION_REVEIL not in {a.nom for a in actions.charger().utilisables}


def test_un_fichier_absent_rend_les_quatre_champs(tmp_path: Path) -> None:
    """L'interface montre toujours quatre champs, fichier ou pas."""
    lignes = actions.lire_lignes(actions.chemin(tmp_path))
    assert [l["action"] for l in lignes] == list(actions.DEFAUTS)


def test_une_action_absente_du_fichier_retombe_sur_son_origine(tmp_path: Path) -> None:
    chemin = ecrire_actions(tmp_path, [ligne("@reveil", "jarvis")])
    jeu = actions.charger(chemin)
    assert jeu.mots_reveil == ("jarvis",)
    assert jeu.action("@quitter").phrases == ("extinction",)


def test_plusieurs_graphies_du_mot_de_reveil(tmp_path: Path) -> None:
    """Le modèle rend un même nom de plusieurs façons : la liste se complète à
    l'oreille, sans qu'aucune ne l'emporte."""
    chemin = ecrire_actions(tmp_path, [ligne("@reveil", "higgins|higuinsse|hidgine")])
    assert actions.charger(chemin).mots_reveil == ("higgins", "higuinsse", "hidgine")


def test_les_formulations_sont_normalisees(tmp_path: Path) -> None:
    chemin = ecrire_actions(tmp_path, [ligne("@reveil", "  Higgins, ")])
    assert actions.charger(chemin).mots_reveil == ("higgins",)


def test_l_extinction_reste_active_meme_decochee(tmp_path: Path) -> None:
    """Le coupe-circuit ne se désactive pas : sans lui, on s'enferme avec une
    télécommande qu'on n'arrête plus à la voix."""
    chemin = ecrire_actions(tmp_path, [ligne("@quitter", "extinction", actif="non")])
    assert actions.charger(chemin).action("@quitter").actif is True


def test_la_pause_se_desactive(tmp_path: Path) -> None:
    chemin = ecrire_actions(tmp_path, [ligne("@pause", "pause", actif="non")])
    jeu = actions.charger(chemin)
    assert jeu.action("@pause").actif is False
    assert "@pause" not in {a.nom for a in jeu.utilisables}


# --- Le mot de réveil changé est entendu -----------------------------------


def test_un_mot_de_reveil_change_atteint_la_grammaire(tmp_path: Path) -> None:
    """La garantie que l'utilisateur attend : ce qu'il écrit ici, l'outil l'entend."""
    ecrire_actions(tmp_path, [ligne("@reveil", "jarvis")])
    (tmp_path / "canva.csv").write_text(
        EN_TETE + "Canva,,suivante,droite,avance,oui\n", encoding="utf-8"
    )

    profil = profils.charger_tous(tmp_path)["canva"]

    assert profil.mots_reveil == ("jarvis",)
    assert "jarvis avance" in profil.grammaire()
    assert not any(e.startswith("higgins") for e in profil.grammaire())


def test_le_meme_jeu_sert_a_tous_les_profils(tmp_path: Path) -> None:
    """C'est tout l'intérêt du fichier commun : plus de profil oublié qui garderait
    l'ancien mot en pleine séance."""
    ecrire_actions(tmp_path, [ligne("@reveil", "jarvis")])
    for nom in ("canva", "defaut"):
        (tmp_path / f"{nom}.csv").write_text(
            EN_TETE + f"{nom},,suivante,droite,avance,oui\n", encoding="utf-8"
        )
    tous = profils.charger_tous(tmp_path)
    assert {p.mots_reveil for p in tous.values()} == {("jarvis",)}


# --- Les refus --------------------------------------------------------------


def test_refus_action_inconnue() -> None:
    [refus] = actions.valider([ligne("@reveille", "higgins")])
    assert refus.colonne == "action"
    assert "@reveil" in refus.message


def test_refus_action_en_double() -> None:
    [refus] = actions.valider([ligne("@pause", "pause"), ligne("@pause", "silence")])
    assert refus.ligne == 3
    assert refus.colonne == "action"


def test_refus_mot_de_reveil_vide() -> None:
    [refus] = actions.valider([ligne("@reveil", "")])
    assert refus.colonne == "phrases"
    assert "phrase de cours" in refus.message


def test_refus_extinction_vide() -> None:
    [refus] = actions.valider([ligne("@quitter", "")])
    assert refus.colonne == "phrases"
    assert "arrêter l'outil à la voix" in refus.message


def test_une_pause_desactivee_peut_rester_vide() -> None:
    assert actions.valider([ligne("@pause", "", actif="non")]) == []


def test_refus_pause_active_sans_formulation() -> None:
    [refus] = actions.valider([ligne("@pause", "", actif="oui")])
    assert refus.colonne == "phrases"


def test_refus_formulation_partagee_entre_deux_actions() -> None:
    [refus] = actions.valider(
        [ligne("@reveil", "higgins"), ligne("@pause", "higgins")]
    )
    assert refus.ligne == 3
    assert "imprévisible" in refus.message


def test_refus_formulation_deja_prise_par_une_commande() -> None:
    """Une action vaut pour tous les profils : elle ne peut reprendre la
    formulation d'aucun d'eux, fût-ce d'un seul."""
    [refus] = actions.valider(
        [ligne("@reveil", "avance")],
        phrases_reservees={"avance": "canva · suivante"},
    )
    assert refus.colonne == "phrases"
    assert "canva · suivante" in refus.message


def test_ce_que_la_validation_accepte_se_charge(tmp_path: Path) -> None:
    lignes = [
        ligne("@reveil", "jarvis|djarvisse"),
        ligne("@pause", "pause"),
        ligne("@reprise", "reprends", actif="non"),
        ligne("@quitter", "extinction"),
    ]
    assert actions.valider(lignes) == []
    chemin = ecrire_actions(tmp_path, lignes)
    jeu = actions.charger(chemin)
    assert jeu.mots_reveil == ("jarvis", "djarvisse")


# --- Un profil ne les redéfinit plus ---------------------------------------


def test_un_profil_qui_declare_une_action_est_refuse(tmp_path: Path) -> None:
    fichier = tmp_path / "vieux.csv"
    fichier.write_text(
        EN_TETE + "Test,,pause,@pause,pause,oui\n", encoding="utf-8"
    )
    with pytest.raises(profils.ErreurProfil, match="_actions.csv"):
        profils.charger(fichier)


def test_une_commande_ne_peut_pas_reprendre_le_mot_de_reveil(tmp_path: Path) -> None:
    fichier = tmp_path / "conflit.csv"
    fichier.write_text(
        EN_TETE + "Test,,reveiller,droite,higgins,oui\n", encoding="utf-8"
    )
    with pytest.raises(profils.ErreurProfil, match="@reveil"):
        profils.charger(fichier)


# --- La reprise, une fois ---------------------------------------------------


def vieux_dossier(tmp_path: Path) -> Path:
    """Un dossier tel qu'il était avant la séparation : les actions dans chaque CSV."""
    (tmp_path / "defaut.csv").write_text(
        EN_TETE
        + "Défaut,,reveil,@reveil,higgins|higuinsse,oui\n"
        + "Défaut,,suivante,droite,avance,oui\n"
        + "Défaut,,pause,@pause,silence,oui\n"
        + "Défaut,,quitter,@quitter,extinction,oui\n",
        encoding="utf-8",
    )
    (tmp_path / "canva.csv").write_text(
        EN_TETE
        + "Canva,com.canva,reveil,@reveil,higgins,oui\n"
        + "Canva,com.canva,noir,b,noir,oui\n",
        encoding="utf-8",
    )
    return tmp_path


def test_la_reprise_sort_les_actions_des_profils(tmp_path: Path) -> None:
    dossier = vieux_dossier(tmp_path)
    assert profils.reprendre_actions(dossier) is True

    jeu = actions.charger(actions.chemin(dossier))
    assert jeu.mots_reveil == ("higgins", "higuinsse")
    assert jeu.action("@pause").phrases == ("silence",)

    for nom in ("defaut", "canva"):
        lignes = profils.lire_lignes(dossier / f"{nom}.csv")
        assert [l for l in lignes if l["touches"].startswith("@")] == []


def test_la_reprise_garde_ce_qui_avait_ete_eprouve(tmp_path: Path) -> None:
    """Les formulations viennent des profils, pas des valeurs d'origine : une
    reprise n'a pas à défaire ce qui a servi en séance."""
    dossier = vieux_dossier(tmp_path)
    profils.reprendre_actions(dossier)
    jeu = actions.charger(actions.chemin(dossier))
    assert "pause" not in jeu.action("@pause").phrases


def test_la_reprise_prend_defaut_en_premier(tmp_path: Path) -> None:
    """Deux profils peuvent avoir divergé ; `defaut` tranche."""
    dossier = vieux_dossier(tmp_path)
    profils.reprendre_actions(dossier)
    assert actions.charger(actions.chemin(dossier)).mots_reveil == (
        "higgins",
        "higuinsse",
    )


def test_la_reprise_ne_se_repete_pas(tmp_path: Path) -> None:
    dossier = vieux_dossier(tmp_path)
    assert profils.reprendre_actions(dossier) is True
    assert profils.reprendre_actions(dossier) is False


def test_la_reprise_ne_recouvre_pas_un_fichier_deja_regle(tmp_path: Path) -> None:
    """Cas réel : l'application copie son `_actions.csv` livré avant que la reprise
    passe. Aux valeurs d'origine, il cède ; réglé, il tient."""
    dossier = vieux_dossier(tmp_path)
    ecrire_actions(dossier, [ligne("@reveil", "jarvis")])

    profils.reprendre_actions(dossier)

    assert actions.charger(actions.chemin(dossier)).mots_reveil == ("jarvis",)
    assert profils.lire_lignes(dossier / "canva.csv")[0]["commande"] == "noir"


def test_la_reprise_laisse_passer_un_dossier_a_jour() -> None:
    assert profils.reprendre_actions(DOSSIER_PROFILS) is False


def test_apres_reprise_les_profils_se_chargent(tmp_path: Path) -> None:
    """La garantie de bout en bout : un vieux dossier redevient utilisable seul."""
    dossier = vieux_dossier(tmp_path)
    profils.reprendre_actions(dossier)
    tous = profils.charger_tous(dossier)
    assert tous["canva"].mots_reveil == ("higgins", "higuinsse")
    assert tous["canva"].resoudre("silence").touches == "@pause"

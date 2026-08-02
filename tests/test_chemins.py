"""Où l'outil lit et où il écrit, selon qu'il tourne depuis le dépôt ou depuis
une application installée.

Ces tests tiennent la promesse qui protège la signature du bundle : rien de ce
que l'utilisateur modifie ne doit se résoudre à l'intérieur du `.app`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from controle_vocal import chemins


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un environnement de développement peut porter ces variables ; les tests
    décident eux-mêmes de ce qu'elles valent."""
    monkeypatch.delenv(chemins.VARIABLE_RESSOURCES, raising=False)
    monkeypatch.delenv(chemins.VARIABLE_PROFILS, raising=False)


# -- détection du bundle ---------------------------------------------------


def test_bundle_absent_depuis_le_depot() -> None:
    assert chemins.bundle() is None


def test_bundle_trouve_le_app_qui_englobe() -> None:
    interieur = Path("/Applications/Contrôle vocal.app/Contents/Resources/paquets/x.py")
    assert chemins.bundle(interieur) == Path("/Applications/Contrôle vocal.app")


def test_bundle_prend_le_app_le_plus_proche() -> None:
    """Un `.app` posé dans un dossier lui-même suffixé `.app` est tiré par les
    cheveux, mais la règle doit rester lisible : le premier parent rencontré."""
    interieur = Path("/a/dehors.app/Contents/Resources/dedans.app/Contents/Resources/x.py")
    assert chemins.bundle(interieur) == Path(
        "/a/dehors.app/Contents/Resources/dedans.app"
    )


def test_bundle_ignore_un_dossier_seulement_nomme_app() -> None:
    assert chemins.bundle(Path("/a/app/b/x.py")) is None


# -- ressources ------------------------------------------------------------


def test_ressources_valent_la_racine_depuis_le_depot() -> None:
    assert chemins.dossier_ressources() == chemins.racine_projet()


def test_ressources_suivent_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(chemins.VARIABLE_RESSOURCES, str(tmp_path))
    assert chemins.dossier_ressources() == tmp_path
    assert chemins.dossier_modeles() == tmp_path / "modeles"


def test_variable_vide_vaut_absente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une variable posée à vide par un script maladroit ne doit pas envoyer
    l'outil lire à la racine du système de fichiers."""
    monkeypatch.setenv(chemins.VARIABLE_RESSOURCES, "   ")
    assert chemins.dossier_ressources() == chemins.racine_projet()


def test_variable_developpe_le_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(chemins.VARIABLE_PROFILS, "~/quelque_part")
    assert chemins.dossier_profils() == Path.home() / "quelque_part"


# -- profils ---------------------------------------------------------------


def test_profils_dans_le_depot_hors_bundle() -> None:
    assert chemins.dossier_profils() == chemins.racine_projet() / "profils"


def test_profils_hors_du_bundle_quand_on_tourne_dans_une_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Le cas qui justifie ce module : depuis une application, les CSV écrits
    par l'interface vont dans le dossier de données, jamais dans le `.app`."""
    app = tmp_path / "Contrôle vocal.app"
    ressources = app / "Contents" / "Resources"
    (ressources / "profils").mkdir(parents=True)
    (ressources / "profils" / "canva.csv").write_text("application\n", encoding="utf-8")

    donnees = tmp_path / "donnees"
    monkeypatch.setattr(chemins, "bundle", lambda depuis=None: app)
    monkeypatch.setattr(chemins, "dossier_donnees", lambda: donnees)

    obtenu = chemins.dossier_profils()

    assert obtenu == donnees / "profils"
    assert app not in obtenu.parents
    assert (obtenu / "canva.csv").exists(), "les profils livrés amorcent le dossier"


def test_profils_sans_amorcage_ne_cree_rien(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "Contrôle vocal.app"
    donnees = tmp_path / "donnees"
    monkeypatch.setattr(chemins, "bundle", lambda depuis=None: app)
    monkeypatch.setattr(chemins, "dossier_donnees", lambda: donnees)

    assert chemins.dossier_profils(amorcer=False) == donnees / "profils"
    assert not donnees.exists()


# -- amorçage --------------------------------------------------------------


def test_amorcer_copie_les_csv_livres(tmp_path: Path) -> None:
    source, cible = tmp_path / "livres", tmp_path / "chez_moi"
    source.mkdir()
    (source / "canva.csv").write_text("un", encoding="utf-8")
    (source / "defaut.csv").write_text("deux", encoding="utf-8")
    (source / "notes.txt").write_text("pas un profil", encoding="utf-8")

    copies = chemins.amorcer_profils(source, cible)

    assert copies == ["canva.csv", "defaut.csv"]
    assert not (cible / "notes.txt").exists()


def test_amorcer_ne_recouvre_jamais_un_profil_existant(tmp_path: Path) -> None:
    """Le cœur de la règle : une mise à jour de l'application ne défait pas les
    réglages éprouvés en séance."""
    source, cible = tmp_path / "livres", tmp_path / "chez_moi"
    source.mkdir()
    cible.mkdir()
    (source / "canva.csv").write_text("livré", encoding="utf-8")
    (cible / "canva.csv").write_text("corrigé par l'utilisateur", encoding="utf-8")

    copies = chemins.amorcer_profils(source, cible)

    assert copies == []
    assert (cible / "canva.csv").read_text(encoding="utf-8") == "corrigé par l'utilisateur"


def test_amorcer_est_idempotent(tmp_path: Path) -> None:
    source, cible = tmp_path / "livres", tmp_path / "chez_moi"
    source.mkdir()
    (source / "canva.csv").write_text("un", encoding="utf-8")

    assert chemins.amorcer_profils(source, cible) == ["canva.csv"]
    assert chemins.amorcer_profils(source, cible) == []


def test_amorcer_sans_source_ne_bronche_pas(tmp_path: Path) -> None:
    """Un bundle fabriqué sans profils livrés reste utilisable : l'interface
    montrera un dossier vide, ce qui se répare, au lieu de planter au lancement."""
    assert chemins.amorcer_profils(tmp_path / "absent", tmp_path / "cible") == []
    assert not (tmp_path / "cible").exists()

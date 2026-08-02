"""Reconnaissance hors ligne à vocabulaire fermé, par Vosk.

Le moteur ne reçoit que les énoncés attendus du profil actif, plus le jeton qui
absorbe le reste : tout ce qui n'y figure pas est rejeté au lieu d'être approché.
Rien ne sort de la machine, rien n'est écrit sur disque.

Essai sur un fichier, sans micro ni action :

    uv run -m controle_vocal.reconnaissance --fichier essai.wav
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from vosk import KaldiRecognizer, Model, SetLogLevel

from controle_vocal import chemins, profils

#: Taux d'échantillonnage attendu par les modèles Vosk français.
TAUX = 16000

#: Jeton que Vosk rend quand il n'a rien reconnu de la grammaire.
TEXTE_INCONNU = profils.JETON_INCONNU

#: Ce que Vosk écrit quand un mot de la grammaire manque à son lexique. Il le
#: retire alors de la grammaire et se tait : sans cette lecture, un mot de réveil
#: mal choisi donnerait une télécommande qui démarre et ne répond jamais.
MOTIF_HORS_LEXIQUE = re.compile(r"Ignoring word missing in vocabulary: '([^']*)'")


@dataclass(frozen=True)
class Enonce:
    """Un segment reconnu, avec la certitude que le moteur lui accorde."""

    texte: str
    certitude: float
    mots: tuple[tuple[str, float], ...]

    @property
    def vide(self) -> bool:
        return not self.texte or self.texte == TEXTE_INCONNU

    @property
    def plancher(self) -> float:
        """Score du mot le plus faible, sur quoi porte le seuil de la décision.

        Mesuré à la voix le 2026-08-02 : la moyenne laisse un mot sûr racheter un
        mot douteux, et c'est ainsi qu'un « higgins pause » fabriqué à partir d'une
        phrase de cours est passé à 0,82. Un énoncé ne vaut que son maillon faible.
        """
        return min((score for _, score in self.mots), default=self.certitude)

    def __str__(self) -> str:
        detail = "  ".join(f"{mot} {score:.2f}" for mot, score in self.mots)
        return f"« {self.texte} »  certitude {self.certitude:.2f}   [{detail}]"


def chemin_modele(nom: str | None = None) -> Path:
    """Trouve le modèle livré. Sans nom donné, prend le seul présent.

    Le dossier vient de `chemins` : la racine du dépôt en développement, les
    ressources du bundle dans une application installée.
    """
    dossier = chemins.dossier_modeles()
    if nom:
        return dossier / nom
    candidats = sorted(c for c in dossier.glob("vosk-model-*") if c.is_dir())
    if not candidats:
        raise FileNotFoundError(
            f"aucun modèle Vosk dans {dossier}. "
            "Voir la commande de téléchargement dans le README."
        )
    return candidats[0]


class Reconnaisseur:
    """Moteur Vosk contraint à la grammaire d'un profil.

    La grammaire se reconstruit en changeant de profil : `changer_grammaire`.
    """

    def __init__(
        self,
        grammaire: list[str],
        modele: Path | None = None,
        taux: int = TAUX,
        bavard: bool = False,
    ) -> None:
        SetLogLevel(0 if bavard else -1)
        self.taux = taux
        self._modele = Model(str(modele or chemin_modele()))
        self._grammaire: list[str] = []
        self.changer_grammaire(grammaire)

    @property
    def grammaire(self) -> list[str]:
        return list(self._grammaire)

    def changer_grammaire(self, grammaire: list[str]) -> None:
        """Repart d'un moteur neuf : un `KaldiRecognizer` porte sa grammaire à vie."""
        self._grammaire = list(grammaire)
        self._moteur = KaldiRecognizer(
            self._modele, self.taux, json.dumps(self._grammaire, ensure_ascii=False)
        )
        self._moteur.SetWords(True)

    def alimenter(self, bloc: bytes) -> Enonce | None:
        """Rend un énoncé quand le moteur juge la phrase terminée, sinon rien."""
        if self._moteur.AcceptWaveform(bloc):
            return self._lire(self._moteur.Result())
        return None

    def reste(self) -> Enonce | None:
        """Vide le moteur en fin de flux, pour ne pas perdre le dernier énoncé."""
        return self._lire(self._moteur.FinalResult())

    @staticmethod
    def _lire(resultat_json: str) -> Enonce | None:
        brut = json.loads(resultat_json)
        texte = (brut.get("text") or "").strip()
        if not texte:
            return None
        mots = tuple(
            (m["word"], float(m.get("conf", 0.0))) for m in brut.get("result", ())
        )
        certitude = sum(score for _, score in mots) / len(mots) if mots else 0.0
        return Enonce(texte=texte, certitude=certitude, mots=mots)


@contextlib.contextmanager
def _capturer_journal() -> Iterator[Path]:
    """Détourne la sortie d'erreur du système pendant le bloc, et rend le fichier.

    Vosk écrit ses avertissements depuis sa couche C++, directement sur le
    descripteur 2 : `contextlib.redirect_stderr`, qui ne remplace que l'objet
    Python, ne les voit pas. Il faut détourner le descripteur lui-même.
    """
    with tempfile.TemporaryFile(mode="w+b") as tampon:
        sys.stderr.flush()
        copie = os.dup(2)
        os.dup2(tampon.fileno(), 2)
        try:
            yield tampon
        finally:
            os.dup2(copie, 2)
            os.close(copie)


_modele_partage: Model | None = None


def modele_partage(chemin: str | Path | None = None) -> Model:
    """Charge le modèle une fois pour tout le processus.

    Il pèse une quarantaine de mégaoctets et met une seconde ou deux à s'ouvrir :
    l'interface de réglages, qui vérifie un mot à chaque enregistrement, ne peut
    pas se le permettre à chaque fois.
    """
    global _modele_partage
    if _modele_partage is None:
        SetLogLevel(-1)
        _modele_partage = Model(str(chemin or chemin_modele()))
    return _modele_partage


def mots_hors_lexique(
    formulations: Iterable[str], modele: Model | None = None
) -> list[str]:
    """Rend les mots que le modèle ne connaît pas, dans l'ordre où ils viennent.

    Un mot absent du lexique n'est pas une erreur pour Vosk : il le retire de la
    grammaire et continue. La télécommande démarre alors sans rien dire et ne
    répond jamais à la formulation concernée. Ce contrôle sert donc à refuser le
    mot au moment où on l'écrit, pas à le découvrir devant la classe.
    """
    grammaire = [f for f in formulations if f]
    if not grammaire:
        return []

    moteur = modele or modele_partage()
    SetLogLevel(0)
    try:
        with _capturer_journal() as journal:
            KaldiRecognizer(
                moteur, TAUX, json.dumps(grammaire + [TEXTE_INCONNU], ensure_ascii=False)
            )
            # Lu à l'intérieur du bloc : le fichier temporaire se ferme en sortant.
            journal.seek(0)
            trace = journal.read().decode("utf-8", errors="replace")
    finally:
        SetLogLevel(-1)

    return list(dict.fromkeys(MOTIF_HORS_LEXIQUE.findall(trace)))


def lire_wav(chemin: str | Path, taille_bloc: int = 4000) -> Iterable[bytes]:
    """Découpe un WAV mono 16 bits en blocs, pour éprouver le moteur sans micro."""
    with wave.open(str(chemin), "rb") as fichier:
        if fichier.getnchannels() != 1 or fichier.getsampwidth() != 2:
            raise ValueError(f"{chemin} : il faut un WAV mono 16 bits")
        while bloc := fichier.readframes(taille_bloc):
            yield bloc


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.reconnaissance",
        description="Affiche tout ce qui est reconnu, sans rien exécuter.",
    )
    analyseur.add_argument(
        "--profil",
        default="canva",
        help="profil dont la grammaire contraint le moteur (défaut : canva)",
    )
    analyseur.add_argument(
        "--fichier",
        metavar="WAV",
        help="éprouve le moteur sur un WAV mono 16 bits au lieu du micro",
    )
    analyseur.add_argument(
        "--grammaire",
        action="store_true",
        help="affiche la grammaire soumise au moteur, puis quitte",
    )
    analyseur.add_argument(
        "--lexique",
        nargs="+",
        metavar="FORMULATION",
        help="dit lesquels de ces mots le modèle ignore, puis quitte",
    )
    analyseur.add_argument(
        "--bavard",
        action="store_true",
        help="laisse Vosk écrire ses propres journaux",
    )
    options = analyseur.parse_args(arguments)

    if options.lexique:
        try:
            inconnus = mots_hors_lexique(options.lexique)
        except FileNotFoundError as erreur:
            print(f"Erreur : {erreur}", file=sys.stderr)
            return 2
        if not inconnus:
            print("Tous ces mots sont dans le lexique du modèle.")
            return 0
        print("Mots que le modèle ignore, et qui ne seront jamais reconnus :")
        for mot in inconnus:
            print(f"  {mot}")
        return 1

    chemin_profil = chemins.dossier_profils() / f"{options.profil}.csv"
    try:
        profil = profils.charger(chemin_profil)
    except profils.ErreurProfil as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    grammaire = profil.grammaire()
    if options.grammaire:
        for entree in grammaire:
            print(entree)
        return 0

    try:
        moteur = Reconnaisseur(grammaire, bavard=options.bavard)
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    if options.fichier:
        for bloc in lire_wav(options.fichier):
            if enonce := moteur.alimenter(bloc):
                print(enonce)
        if enonce := moteur.reste():
            print(enonce)
        return 0

    from controle_vocal import audio

    print(
        f"Écoute en cours, profil « {profil.nom} », Ctrl+C pour arrêter.\n"
        f"Rien n'est exécuté : cet essai affiche seulement ce qui est reconnu."
    )
    try:
        with audio.Micro(taux=moteur.taux) as micro:
            for bloc in micro:
                if enonce := moteur.alimenter(bloc):
                    print(f"  {enonce}")
    except audio.ErreurMicro as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if enonce := moteur.reste():
            print(f"  {enonce}")
        print("\nÉcoute arrêtée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

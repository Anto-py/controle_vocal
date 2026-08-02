"""Conduite de la boucle d'écoute depuis l'interface : la lancer, l'arrêter, dire
si elle tourne.

Le serveur de réglages devient le parent de l'outil. Trois choses en découlent, et
ce module les tient toutes les trois plutôt que de les laisser à l'appelant :

- **La sortie de l'enfant est lue en continu.** Un tuyau qu'on ne vide pas finit
  plein, et l'enfant se bloque en écrivant dedans. Les dernières lignes sont
  gardées, ce sont elles qui disent pourquoi un lancement a échoué.
- **Un enfant mort est vu comme mort.** L'état est relu du système à chaque
  demande, jamais gardé en mémoire : le micro peut disparaître en séance, et un
  bouton qui afficherait encore « en marche » serait pire que pas de bouton.
- **L'arrêt commence par un Ctrl+C.** `SIGINT` est le signal que la boucle sait
  traiter, elle ferme le micro et la pastille ; `SIGTERM` puis `SIGKILL` ne
  servent que si elle ne répond pas.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from collections import deque
from pathlib import Path

#: Lignes de sortie gardées de l'outil. De quoi montrer un message d'échec au
#: lancement sans conserver toute une séance de traces.
LIGNES_GARDEES = 40

#: Temps laissé à la boucle pour se fermer après Ctrl+C, puis après SIGTERM.
DELAI_ARRET_DOUX = 3.0
DELAI_ARRET_FERME = 2.0


class ErreurMoteur(Exception):
    """Lancement ou arrêt impossible, avec un message destiné à l'écran."""


def argv_par_defaut(profil: str | None, pastille: bool) -> list[str]:
    """Commande réelle. `sys.executable` est le Python de l'environnement du
    projet : l'outil hérite des dépendances sans repasser par `uv`."""
    argv = [sys.executable, "-m", "controle_vocal"]
    if profil:
        argv += ["--profil", profil]
    if pastille:
        argv.append("--pastille")
    return argv


class Moteur:
    """Le processus d'écoute, vu depuis l'interface."""

    def __init__(
        self,
        racine: str | Path,
        fabriquer_argv: Callable[[str | None, bool], Sequence[str]] = argv_par_defaut,
    ) -> None:
        self.racine = Path(racine)
        self.fabriquer_argv = fabriquer_argv
        self._processus: subprocess.Popen[str] | None = None
        self._lignes: deque[str] = deque(maxlen=LIGNES_GARDEES)
        self._options: dict[str, object] = {}
        self._verrou = threading.Lock()

    # -- état -------------------------------------------------------------

    @property
    def actif(self) -> bool:
        """Interroge le système plutôt que la mémoire : un outil qui s'est arrêté
        tout seul, micro débranché ou `extinction` dite à la voix, doit apparaître
        arrêté."""
        return self._processus is not None and self._processus.poll() is None

    def etat(self) -> dict[str, object]:
        processus = self._processus
        code = processus.poll() if processus is not None else None
        return {
            "actif": self.actif,
            "pid": processus.pid if processus is not None and self.actif else None,
            "code_retour": code if processus is not None and not self.actif else None,
            "options": dict(self._options),
            "journal": list(self._lignes),
        }

    # -- conduite ---------------------------------------------------------

    def demarrer(self, profil: str | None = None, pastille: bool = False) -> None:
        with self._verrou:
            if self.actif:
                raise ErreurMoteur("l'outil tourne déjà")

            argv = list(self.fabriquer_argv(profil, pastille))
            self._lignes.clear()
            self._options = {"profil": profil, "pastille": pastille}

            # Python met sa sortie en tampon dès qu'elle part dans un tuyau plutôt
            # que dans un terminal : sans cette variable, les messages de l'outil
            # n'arriveraient qu'à sa mort, et l'interface ne montrerait rien
            # pendant qu'il tourne. Vérifié à l'essai, le journal restait vide.
            environnement = {**os.environ, "PYTHONUNBUFFERED": "1"}

            try:
                self._processus = subprocess.Popen(  # noqa: S603 - argv fixe, sans shell
                    argv,
                    cwd=self.racine,
                    env=environnement,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as erreur:
                self._processus = None
                raise ErreurMoteur(f"lancement impossible : {erreur}") from erreur

            fil = threading.Thread(
                target=self._lire_sortie, args=(self._processus,), daemon=True
            )
            fil.start()

    def _lire_sortie(self, processus: subprocess.Popen[str]) -> None:
        """Vide le tuyau en continu, sans quoi l'enfant se bloquerait en écrivant."""
        if processus.stdout is None:
            return
        for ligne in processus.stdout:
            self._lignes.append(ligne.rstrip("\n"))

    def arreter(self) -> None:
        with self._verrou:
            processus = self._processus
            if processus is None or processus.poll() is not None:
                raise ErreurMoteur("l'outil ne tourne pas")

            for signal_, delai in (
                (signal.SIGINT, DELAI_ARRET_DOUX),
                (signal.SIGTERM, DELAI_ARRET_FERME),
            ):
                self._envoyer(processus, signal_)
                try:
                    processus.wait(timeout=delai)
                    return
                except subprocess.TimeoutExpired:
                    continue

            self._envoyer(processus, signal.SIGKILL)
            processus.wait(timeout=DELAI_ARRET_FERME)

    @staticmethod
    def _envoyer(processus: subprocess.Popen[str], signal_: int) -> None:
        """Vise le groupe de processus, `start_new_session` en ayant fait le chef :
        un outil qui aurait lui-même lancé quelque chose part avec lui."""
        try:
            os.killpg(os.getpgid(processus.pid), signal_)
        except (ProcessLookupError, PermissionError):
            processus.send_signal(signal_)

    def fermer(self) -> None:
        """Arrêt sans erreur si rien ne tourne : appelé quand le serveur s'éteint,
        pour ne pas laisser l'outil écouter le micro sans personne pour le couper."""
        try:
            self.arreter()
        except ErreurMoteur:
            pass

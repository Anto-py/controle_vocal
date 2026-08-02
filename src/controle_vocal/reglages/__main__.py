"""Serveur local de l'interface de réglages.

    uv run -m controle_vocal.reglages              ouvre la page dans le navigateur
    uv run -m controle_vocal.reglages --port 9000  autre port
    uv run -m controle_vocal.reglages --sans-navigateur

À lancer avant un exposé, jamais pendant : la boucle d'écoute ne dépend pas de ce
serveur, et relit ses CSV à chaque changement de profil. Un profil modifié ici est
donc pris sans rien redémarrer.

L'écoute est liée à `127.0.0.1` et à rien d'autre : une interface qui écrit des
fichiers n'a pas à être joignable depuis le réseau de la salle.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from controle_vocal.reglages.moteur import Moteur
from controle_vocal.reglages.serveur import PORT_PAR_DEFAUT, Reglages, router

ADRESSE_LOCALE = "127.0.0.1"

DOSSIER_PROFILS = Path(__file__).resolve().parents[3] / "profils"

#: Taille maximale d'un corps de requête. Un profil pèse un kilo-octet ; au-delà du
#: mégaoctet, c'est une erreur, pas un CSV.
CORPS_MAXIMAL = 1_000_000


def _clavier():  # noqa: ANN202 - le module ou rien, selon la plateforme
    """Rend le module `clavier` si PyObjC répond, sinon rien.

    Il porte les deux seuls liens de cette interface avec macOS, le contrôle des
    touches et l'autorisation Accessibilité. Hors macOS, elle reste utilisable :
    tous les autres refus tiennent, et l'état d'autorisation n'a pas de sens.
    """
    try:
        from controle_vocal import clavier
    except Exception:  # noqa: BLE001 - PyObjC absent
        return None
    return clavier


class Poignee(BaseHTTPRequestHandler):
    """Coquille autour de `router` : elle ne décide de rien."""

    server_version = "controle_vocal"
    reglages: Reglages

    def _repondre(self, methode: str) -> None:
        longueur = int(self.headers.get("Content-Length") or 0)
        if longueur > CORPS_MAXIMAL:
            self.send_error(413, "corps de requête trop grand")
            return
        corps = self.rfile.read(longueur) if longueur else b""
        reponse = router(self.reglages, methode, self.path, corps)
        self.send_response(reponse.code)
        self.send_header("Content-Type", reponse.type_contenu)
        self.send_header("Content-Length", str(len(reponse.corps)))
        self.end_headers()
        self.wfile.write(reponse.corps)

    def do_GET(self) -> None:  # noqa: N802 - imposé par BaseHTTPRequestHandler
        self._repondre("GET")

    def do_PUT(self) -> None:  # noqa: N802
        self._repondre("PUT")

    def do_POST(self) -> None:  # noqa: N802
        self._repondre("POST")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Une ligne par requête, sur la sortie d'erreur, sans horodatage bavard."""
        print(f"  {format % args}", file=sys.stderr)


def _analyser(arguments: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.reglages",
        description="Interface web locale pour éditer les profils.",
    )
    analyseur.add_argument("--port", type=int, default=PORT_PAR_DEFAUT)
    analyseur.add_argument(
        "--profils", type=Path, default=DOSSIER_PROFILS, help="dossier des CSV"
    )
    analyseur.add_argument(
        "--sans-navigateur", action="store_true", help="ne pas ouvrir la page"
    )
    return analyseur.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _analyser(arguments)

    if not options.profils.is_dir():
        print(f"Dossier de profils introuvable : {options.profils}", file=sys.stderr)
        return 1

    clavier = _clavier()
    moteur = Moteur(racine=options.profils.parent)
    reglages = Reglages(
        options.profils,
        verifier_touche=clavier.analyser if clavier else None,
        moteur=moteur,
        lire_accessibilite=clavier.accessibilite_accordee if clavier else None,
        demander_accessibilite=clavier.demander_accessibilite if clavier else None,
    )
    Poignee.reglages = reglages

    try:
        serveur = HTTPServer((ADRESSE_LOCALE, options.port), Poignee)
    except OSError as erreur:
        print(
            f"Port {options.port} indisponible ({erreur}).\n"
            "Une autre instance tourne peut-être déjà, ou choisir --port.",
            file=sys.stderr,
        )
        return 1

    # `shutdown` bloque tant que `serve_forever` tourne : il ne peut pas être appelé
    # depuis le fil qui traite la requête, d'où le fil dédié.
    reglages.arreter_serveur = lambda: threading.Thread(
        target=serveur.shutdown, daemon=True
    ).start()

    adresse = f"http://{ADRESSE_LOCALE}:{options.port}/"
    nombre = len(list(options.profils.glob("*.csv")))
    print(f"Réglages sur {adresse}  ({nombre} fichiers dans {options.profils})")
    print("Ctrl+C pour arrêter.")

    if not options.sans_navigateur:
        threading.Timer(0.3, webbrowser.open, args=[adresse]).start()

    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        # L'outil ne survit pas à l'interface qui l'a lancé : sans cela, le micro
        # resterait ouvert sans personne pour le couper.
        if moteur.actif:
            print("Arrêt de l'outil en cours...")
            moteur.fermer()
        serveur.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

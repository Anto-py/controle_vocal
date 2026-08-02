"""Routes de l'interface de réglages, et la logique qu'elles appellent.

Trois couches empilées, la plus basse ne connaissant pas la plus haute :

1. `Reglages` lit et écrit les profils, sans rien savoir du web. Le contrôle des
   touches lui est injecté, ce qui la rend éprouvable sans macOS.
2. `router` traduit une requête en réponse, sans rien savoir de `http.server`.
   C'est la couche que les tests appellent : ni port ouvert, ni navigateur.
3. `Poignee`, dans `__main__.py`, n'est qu'une coquille autour de `router`.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from controle_vocal import actions, profils, tableaux
from controle_vocal.reglages.moteur import ErreurMoteur, Moteur

#: Port de la boucle locale. Fixe, pour que le signet reste valable.
PORT_PAR_DEFAUT = 8730

DOSSIER_STATIQUE = Path(__file__).resolve().parent / "statique"

#: Un nom de profil désigne un fichier de `profils/`, jamais un chemin : la
#: convention du vault (minuscules et souligné) fait ici office de garde-fou
#: contre la traversée de répertoire.
NOM_DE_PROFIL = re.compile(r"^[a-z0-9_]{1,64}$")

TYPES_STATIQUES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}


class ErreurRequete(Exception):
    """Requête refusée, avec le code HTTP qui lui convient."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Reponse:
    code: int
    type_contenu: str
    corps: bytes

    @classmethod
    def json(cls, charge: object, code: int = 200) -> Reponse:
        texte = json.dumps(charge, ensure_ascii=False, indent=None)
        return cls(code, "application/json; charset=utf-8", texte.encode("utf-8"))

    @classmethod
    def csv(cls, texte: str, nom_fichier: str) -> Reponse:
        return cls(200, f"text/csv; charset=utf-8; nom={nom_fichier}", texte.encode("utf-8"))


class Reglages:
    """Lecture et écriture des profils d'un dossier, sans couche web."""

    def __init__(
        self,
        dossier: str | Path,
        verifier_touche: Callable[[str], None] | None = None,
        moteur: Moteur | None = None,
        arreter_serveur: Callable[[], None] | None = None,
        lire_accessibilite: Callable[[], bool] | None = None,
        demander_accessibilite: Callable[[], bool] | None = None,
        verifier_lexique: Callable[[Iterable[str]], list[str]] | None = None,
    ) -> None:
        self.dossier = Path(dossier)
        self.verifier_touche = verifier_touche
        self.moteur = moteur
        self.arreter_serveur = arreter_serveur
        self.lire_accessibilite = lire_accessibilite
        self.demander_accessibilite = demander_accessibilite
        self.verifier_lexique = verifier_lexique

    # -- chemins ----------------------------------------------------------

    def chemin(self, nom: str) -> Path:
        if not NOM_DE_PROFIL.match(nom):
            raise ErreurRequete(
                400,
                f"nom de profil refusé : « {nom} ». "
                "Minuscules, chiffres et soulignés seulement, sans chemin ni extension.",
            )
        return self.dossier / f"{nom}.csv"

    # -- lecture ----------------------------------------------------------

    def liste(self) -> list[dict[str, object]]:
        """Les profils du dossier, gabarit exclu : il n'a que ses en-têtes."""
        resume = []
        for chemin in sorted(self.dossier.glob("*.csv")):
            if chemin.name.startswith("_"):
                continue
            try:
                lignes = profils.lire_lignes(chemin)
            except profils.ErreurProfil as erreur:
                resume.append(
                    {"nom": chemin.stem, "erreur": str(erreur), "commandes": 0}
                )
                continue
            resume.append(
                {
                    "nom": chemin.stem,
                    "application": next(
                        (l["application"] for l in lignes if l["application"]), chemin.stem
                    ),
                    "bundle_id": next(
                        (l["bundle_id"] for l in lignes if l["bundle_id"]), ""
                    ),
                    "commandes": sum(1 for l in lignes if profils.est_actif(l)),
                    "total": len(lignes),
                }
            )
        return resume

    def lire(self, nom: str) -> list[dict[str, str]]:
        chemin = self.chemin(nom)
        if not chemin.exists():
            raise ErreurRequete(404, f"profil inconnu : « {nom} »")
        try:
            return profils.lire_lignes(chemin)
        except profils.ErreurProfil as erreur:
            raise ErreurRequete(422, str(erreur)) from erreur

    def exporter(self, nom: str) -> str:
        chemin = self.chemin(nom)
        if not chemin.exists():
            raise ErreurRequete(404, f"profil inconnu : « {nom} »")
        return chemin.read_text(encoding="utf-8")

    def gabarit(self) -> str:
        gabarit = self.dossier / "_gabarit.csv"
        if gabarit.exists():
            return gabarit.read_text(encoding="utf-8")
        return profils.rendre_csv([])

    def touches_connues(self) -> dict[str, list[str]]:
        """Sert la liste déroulante de la page. Vide si le clavier n'est pas
        disponible, ce qui arrive hors macOS : la page reste utilisable, en saisie
        libre, et la validation garde le dernier mot à l'enregistrement.

        Les actions internes n'y figurent pas : elles ne s'écrivent plus dans un
        profil, et les proposer ici mènerait droit à un refus.
        """
        try:
            from controle_vocal import clavier
        except Exception:  # noqa: BLE001 - hors macOS, PyObjC manque
            return {"touches": [], "modificateurs": []}
        return {
            "touches": sorted(clavier.TOUCHES),
            "modificateurs": sorted(clavier.MODIFICATEURS),
        }

    # -- actions internes -------------------------------------------------

    @property
    def chemin_actions(self) -> Path:
        return actions.chemin(self.dossier)

    def lire_actions(self) -> dict[str, object]:
        """Les quatre actions et de quoi les présenter, en une seule requête."""
        try:
            lignes = actions.lire_lignes(self.chemin_actions)
        except actions.ErreurActions as erreur:
            raise ErreurRequete(422, str(erreur)) from erreur
        return {
            "lignes": lignes,
            "libelles": {
                nom: {"titre": titre, "detail": detail}
                for nom, (titre, detail) in actions.LIBELLES.items()
            },
            "toujours_actives": sorted(actions.TOUJOURS_ACTIVES),
        }

    def phrases_des_profils(self) -> dict[str, str]:
        """Formulations déjà prises par les commandes, tous profils confondus.

        Une action interne vaut pour tous les profils : elle ne peut donc reprendre
        aucune de leurs formulations, fût-ce dans un seul d'entre eux.
        """
        prises: dict[str, str] = {}
        for chemin in sorted(self.dossier.glob("*.csv")):
            if chemin.name.startswith("_"):
                continue
            try:
                lignes = profils.lire_lignes(chemin)
            except profils.ErreurProfil:
                continue
            for ligne in lignes:
                if not (profils.est_actif(ligne) and ligne["touches"].strip()):
                    continue
                for phrase in tableaux.decouper_phrases(ligne["phrases"]):
                    prises.setdefault(
                        phrase, f"{chemin.stem} · {ligne['commande'].strip()}"
                    )
        return prises

    def enregistrer_actions(self, lignes: list[Mapping[str, str]]) -> list[profils.Refus]:
        """Valide puis écrit les actions internes. Sur refus, le fichier est intact.

        Le contrôle du lexique vient en dernier, une fois la forme acquise : il
        demande de charger le modèle Vosk, ce qui ne se fait pas pour un fichier
        qu'on va refuser de toute façon.
        """
        refus = actions.valider(lignes, phrases_reservees=self.phrases_des_profils())
        if not refus:
            refus = self._refus_de_lexique(lignes)
        if refus:
            return refus
        actions.ecrire(self.chemin_actions, lignes)
        return []

    def _refus_de_lexique(self, lignes: list[Mapping[str, str]]) -> list[profils.Refus]:
        """Refuse les mots que le modèle ignore : il les retire de la grammaire
        sans rien dire, et la formulation ne serait jamais reconnue."""
        if self.verifier_lexique is None:
            return []
        refus = []
        for numero, ligne in enumerate(lignes, start=2):
            if not tableaux.vrai_faux(ligne.get("actif", "")) and (
                ligne.get("action", "").strip() not in actions.TOUJOURS_ACTIVES
            ):
                continue
            inconnus = self.verifier_lexique(
                tableaux.decouper_phrases(ligne.get("phrases", ""))
            )
            if inconnus:
                mots = ", ".join(f"« {mot} »" for mot in inconnus)
                refus.append(
                    profils.Refus(
                        numero,
                        "phrases",
                        f"le modèle français ne connaît pas {mots} : il ne le "
                        "reconnaîtra jamais. Prendre un mot ou un prénom du "
                        "français courant, qu'on ne dit pas en cours.",
                    )
                )
        return refus

    # -- écriture ---------------------------------------------------------

    def enregistrer(self, nom: str, lignes: list[Mapping[str, str]]) -> list[profils.Refus]:
        """Valide puis écrit. Sur refus, le fichier n'est pas touché.

        C'est toute la raison d'être de cette interface face à un éditeur de texte :
        ce qu'elle accepte ne peut pas faire échouer un lancement.
        """
        chemin = self.chemin(nom)
        try:
            jeu = actions.charger(self.chemin_actions)
        except actions.ErreurActions as erreur:
            raise ErreurRequete(422, str(erreur)) from erreur
        refus = profils.valider(
            lignes,
            verifier_touche=self.verifier_touche,
            phrases_reservees=jeu.phrases_prises(),
        )
        if refus:
            return refus
        profils.ecrire(chemin, lignes)
        return []

    def importer(self, nom: str, texte_csv: str) -> list[profils.Refus]:
        """Remplace un profil par un CSV venu d'ailleurs, mêmes contrôles."""
        lecteur = csv.DictReader(io.StringIO(texte_csv))
        manquantes = set(profils.COLONNES) - set(lecteur.fieldnames or ())
        if manquantes:
            return [
                profils.Refus(
                    0,
                    "",
                    f"colonnes absentes : {sorted(manquantes)}. "
                    f"Attendues : {list(profils.COLONNES)}. Partir du gabarit.",
                )
            ]
        lignes = [
            {colonne: (ligne.get(colonne) or "") for colonne in profils.COLONNES}
            for ligne in lecteur
        ]
        return self.enregistrer(nom, lignes)


def _refus_en_json(refus: list[profils.Refus]) -> Reponse:
    return Reponse.json(
        {
            "refus": [
                {"ligne": r.ligne, "colonne": r.colonne, "message": r.message}
                for r in refus
            ]
        },
        code=422,
    )


def _statique(chemin: str) -> Reponse:
    """Sert la page et ses ressources, sans jamais sortir du dossier `statique`."""
    relatif = "index.html" if chemin in ("", "/") else chemin.lstrip("/")
    cible = (DOSSIER_STATIQUE / relatif).resolve()
    if not cible.is_file() or DOSSIER_STATIQUE not in cible.parents:
        raise ErreurRequete(404, f"ressource inconnue : {chemin}")
    type_contenu = TYPES_STATIQUES.get(cible.suffix, "application/octet-stream")
    return Reponse(200, type_contenu, cible.read_bytes())


def router(reglages: Reglages, methode: str, chemin: str, corps: bytes = b"") -> Reponse:
    """Traduit une requête en réponse. Aucun port, aucun socket : testable tel quel."""
    try:
        return _router(reglages, methode, chemin, corps)
    except ErreurRequete as erreur:
        return Reponse.json({"erreur": erreur.message}, code=erreur.code)


def _charge_json(corps: bytes) -> object:
    try:
        return json.loads(corps.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erreur:
        raise ErreurRequete(400, f"corps de requête illisible : {erreur}") from erreur


def _router_moteur(reglages: Reglages, methode: str, reste: str, corps: bytes) -> Reponse:
    """Marche et arrêt de la boucle d'écoute.

    Le profil demandé passe par le même contrôle de nom que l'édition : il finira
    en argument d'un processus, et rien qui vienne du navigateur ne doit pouvoir
    désigner autre chose qu'un fichier de `profils/`.
    """
    if reglages.moteur is None:
        raise ErreurRequete(501, "cette interface ne conduit pas l'outil")

    if reste == "moteur" and methode == "GET":
        return Reponse.json(reglages.moteur.etat())

    if reste == "moteur/demarrer" and methode == "POST":
        charge = _charge_json(corps) if corps else {}
        if not isinstance(charge, dict):
            raise ErreurRequete(400, "corps attendu : un objet JSON")
        profil = charge.get("profil") or None
        if profil is not None:
            reglages.chemin(profil)  # lève si le nom sort de la convention
            if not (reglages.dossier / f"{profil}.csv").exists():
                raise ErreurRequete(404, f"profil inconnu : « {profil} »")
        try:
            reglages.moteur.demarrer(profil=profil, pastille=bool(charge.get("pastille")))
        except ErreurMoteur as erreur:
            raise ErreurRequete(409, str(erreur)) from erreur
        return Reponse.json(reglages.moteur.etat())

    if reste == "moteur/arreter" and methode == "POST":
        try:
            reglages.moteur.arreter()
        except ErreurMoteur as erreur:
            raise ErreurRequete(409, str(erreur)) from erreur
        return Reponse.json(reglages.moteur.etat())

    raise ErreurRequete(404, f"route inconnue : {methode} /api/{reste}")


def _router_accessibilite(reglages: Reglages, methode: str, reste: str) -> Reponse:
    """État de l'autorisation macOS, et demande de celle-ci.

    Distinction qui commande ces deux routes : lire l'état n'inscrit rien dans le
    panneau des Réglages système, seule la demande le fait. Une application qui
    ne demande jamais n'y figure jamais.
    """
    if reglages.lire_accessibilite is None:
        raise ErreurRequete(501, "autorisation non consultable hors macOS")

    if reste == "accessibilite" and methode == "GET":
        return Reponse.json({"accordee": reglages.lire_accessibilite()})

    if reste == "accessibilite/demander" and methode == "POST":
        if reglages.demander_accessibilite is None:
            raise ErreurRequete(501, "autorisation non demandable")
        return Reponse.json({"accordee": reglages.demander_accessibilite()})

    raise ErreurRequete(404, f"route inconnue : {methode} /api/{reste}")


def _router(reglages: Reglages, methode: str, chemin: str, corps: bytes) -> Reponse:
    if not chemin.startswith("/api/"):
        if methode != "GET":
            raise ErreurRequete(405, f"méthode refusée : {methode}")
        return _statique(chemin)

    reste = chemin.removeprefix("/api/")

    if reste.startswith("moteur"):
        return _router_moteur(reglages, methode, reste, corps)

    if reste.startswith("accessibilite"):
        return _router_accessibilite(reglages, methode, reste)

    if reste == "quitter" and methode == "POST":
        # Lancée depuis une application du Dock, l'interface n'a pas de terminal où
        # faire Ctrl+C : elle doit pouvoir se fermer elle-même, et emmener l'outil.
        if reglages.arreter_serveur is None:
            raise ErreurRequete(501, "cette interface ne peut pas se fermer elle-même")
        reglages.arreter_serveur()
        return Reponse.json({"ferme": True})

    if reste == "touches" and methode == "GET":
        return Reponse.json(reglages.touches_connues())

    if reste == "actions":
        # Les quatre mots de l'outil, communs à tous les profils : ils ont leur
        # route parce qu'ils ont leur fichier, et parce qu'un profil enregistré
        # n'a pas à les réécrire.
        if methode == "GET":
            return Reponse.json(reglages.lire_actions())
        if methode == "PUT":
            charge = _charge_json(corps)
            if not isinstance(charge, dict) or not isinstance(charge.get("lignes"), list):
                raise ErreurRequete(400, 'corps attendu : { "lignes": [...] }')
            if refus := reglages.enregistrer_actions(charge["lignes"]):
                return _refus_en_json(refus)
            return Reponse.json({"enregistre": actions.FICHIER})
        raise ErreurRequete(405, f"méthode refusée : {methode}")

    if reste == "gabarit" and methode == "GET":
        return Reponse.csv(reglages.gabarit(), "_gabarit.csv")

    if reste == "profils" and methode == "GET":
        # Le dossier accompagne la liste : installée en application, l'interface
        # édite des fichiers rangés dans la bibliothèque de l'utilisateur, que
        # personne ne devinerait. Depuis le dépôt, il rappelle simplement que ce
        # sont les CSV versionnés qu'on modifie.
        return Reponse.json(
            {"profils": reglages.liste(), "dossier": str(reglages.dossier)}
        )

    if reste.startswith("profils/"):
        morceaux = reste.removeprefix("profils/").split("/")
        nom = morceaux[0]
        action = morceaux[1] if len(morceaux) > 1 else ""

        if not action and methode == "GET":
            return Reponse.json({"nom": nom, "lignes": reglages.lire(nom)})

        if not action and methode == "PUT":
            charge = _charge_json(corps)
            if not isinstance(charge, dict) or not isinstance(charge.get("lignes"), list):
                raise ErreurRequete(400, "corps attendu : { \"lignes\": [...] }")
            if refus := reglages.enregistrer(nom, charge["lignes"]):
                return _refus_en_json(refus)
            return Reponse.json({"enregistre": nom, "lignes": len(charge["lignes"])})

        if action == "export" and methode == "GET":
            return Reponse.csv(reglages.exporter(nom), f"{nom}.csv")

        if action == "import" and methode == "POST":
            if refus := reglages.importer(nom, corps.decode("utf-8", errors="replace")):
                return _refus_en_json(refus)
            return Reponse.json({"importe": nom})

    raise ErreurRequete(404, f"route inconnue : {methode} {chemin}")

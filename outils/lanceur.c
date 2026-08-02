/* Exécutable de « Contrôle vocal.app ».
 *
 * Pourquoi un binaire compilé plutôt qu'un script shell, qui suffisait à lancer
 * un serveur : macOS n'accorde pas d'autorisation à un script. Le processus qui
 * tourne alors est /bin/bash, un binaire d'Apple, et lui attribuer l'accès à
 * l'Accessibilité reviendrait à l'accorder à tout script du système. L'app
 * n'apparaissait donc jamais dans le panneau des Réglages système, et empruntait
 * l'autorisation d'un autre maillon de sa chaîne.
 *
 * Deuxième raison d'être de ce fichier, et elle commande sa structure : le
 * lanceur ne se remplace PAS par l'interpréteur (pas d'exec direct). Il duplique
 * le processus et attend son enfant. Le binaire signé reste ainsi vivant pendant
 * toute la séance, et c'est lui que le système tient pour responsable de ce que
 * fait sa descendance. Un exec l'aurait effacé, avec l'identité qu'on cherche
 * précisément à lui donner.
 *
 * Le même binaire sert les deux façons de fabriquer l'app, et il ne le demande à
 * personne : il regarde s'il a un interpréteur à côté de lui.
 *
 * - **App autonome** : Contents/Resources/python existe. L'app se suffit, elle
 *   part sur n'importe quel Mac, et rien ne la lie à un dossier de projet.
 * - **App liée au dépôt** : pas d'interpréteur embarqué, on retombe sur les
 *   chemins figés à la compilation, uv et le projet. Commode en développement,
 *   le code de l'app suit celui qu'on édite.
 *
 * Se situer soi-même plutôt que se faire dire où l'on est : une app se déplace,
 * de /Applications au dossier d'un collègue, et aucun chemin inscrit à la
 * fabrication ne survivrait au voyage.
 *
 * Compilé par outils/fabriquer_app.py.
 */

#include <arpa/inet.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef PROJET
#define PROJET "."
#endif
#ifndef CHEMIN_UV
#define CHEMIN_UV "/opt/homebrew/bin/uv"
#endif
#ifndef PORT
#define PORT 8730
#endif

/* Une app lancée depuis le Finder n'a pas de terminal où écrire : sans cette
 * alerte, tout échec la ferait disparaître en silence. */
static void alerte(const char *message) {
    char commande[2048];
    snprintf(commande, sizeof commande,
             "/usr/bin/osascript -e 'display alert \"Contrôle vocal\" message \"%s\" "
             "as critical' >/dev/null 2>&1",
             message);
    system(commande);
}

/* Un second double-clic ne doit pas lancer un serveur de plus : le port serait
 * pris, et l'app échouerait sur un geste distrait. */
static int serveur_deja_la(void) {
    int prise = socket(AF_INET, SOCK_STREAM, 0);
    if (prise < 0) {
        return 0;
    }
    struct sockaddr_in adresse;
    memset(&adresse, 0, sizeof adresse);
    adresse.sin_family = AF_INET;
    adresse.sin_port = htons(PORT);
    adresse.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int joignable = connect(prise, (struct sockaddr *)&adresse, sizeof adresse) == 0;
    close(prise);
    return joignable;
}

/* Contents/Resources de l'app dont ce binaire est l'exécutable, déduit de son
 * propre chemin : Contents/MacOS/lancer, deux dossiers à remonter. */
static int trouver_ressources(char *sortie, size_t taille) {
    char brut[PATH_MAX];
    uint32_t large = sizeof brut;
    if (_NSGetExecutablePath(brut, &large) != 0) {
        return 0;
    }
    char resolu[PATH_MAX];
    if (realpath(brut, resolu) == NULL) {
        return 0;
    }
    char *macos = dirname(resolu);      /* .../Contents/MacOS  */
    char *contents = dirname(macos);    /* .../Contents        */
    return snprintf(sortie, taille, "%s/Resources", contents) < (int)taille;
}

static int existe(const char *chemin) {
    struct stat etat;
    return stat(chemin, &etat) == 0;
}

int main(void) {
    if (serveur_deja_la()) {
        char commande[256];
        snprintf(commande, sizeof commande, "/usr/bin/open http://127.0.0.1:%d/", PORT);
        system(commande);
        return 0;
    }

    char ressources[PATH_MAX];
    char interprete[PATH_MAX];
    int autonome = 0;
    if (trouver_ressources(ressources, sizeof ressources)) {
        snprintf(interprete, sizeof interprete, "%s/python/bin/python3", ressources);
        autonome = existe(interprete);
    }

    if (!autonome && chdir(PROJET) != 0) {
        alerte("Le dossier du projet est introuvable. Refabriquer l'application, "
               "ou la fabriquer en mode autonome pour qu'elle se passe du projet.");
        return 1;
    }
    if (autonome) {
        chdir(ressources);
    }

    pid_t enfant = fork();
    if (enfant < 0) {
        alerte("Lancement impossible : le système a refusé de créer le processus.");
        return 1;
    }

    if (enfant == 0) {
        /* Le port est dit au serveur, et pas seulement guetté ici : sans cela,
         * une app fabriquée sur un autre port surveillerait une porte pendant
         * que le serveur en ouvre une autre, et chaque double-clic lancerait une
         * instance de plus. */
        char port[16];
        snprintf(port, sizeof port, "%d", PORT);
        if (autonome) {
            /* Le code embarqué doit trouver ses modèles dans le bundle. Les
             * profils, eux, ne s'annoncent pas : le module chemins les place
             * dans le dossier de données de l'utilisateur, parce qu'écrire dans
             * un bundle signé le casserait. */
            setenv("CONTROLE_VOCAL_RESSOURCES", ressources, 1);
            /* Interdiction d'écrire des .pyc : ils iraient dans le bundle, dont
             * le sceau couvre chaque fichier. Une écriture, et l'application
             * perd l'identité qui porte son autorisation Accessibilité. Les
             * fichiers compilés sont posés à la fabrication, avant la signature. */
            setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
            execl(interprete, "python3", "-m", "controle_vocal.reglages", "--port", port,
                  (char *)NULL);
        } else {
            execl(CHEMIN_UV, "uv", "run", "-m", "controle_vocal.reglages", "--port", port,
                  (char *)NULL);
        }
        _exit(127); /* l'interpréteur est introuvable : le parent le traduira. */
    }

    int etat = 0;
    if (waitpid(enfant, &etat, 0) < 0) {
        return 1;
    }
    if (WIFEXITED(etat) && WEXITSTATUS(etat) == 127) {
        alerte(autonome
                   ? "L'interpréteur embarqué est introuvable. L'application est "
                     "incomplète : en redemander une copie."
                   : "uv est introuvable. Le réinstaller, puis refabriquer "
                     "l'application.");
        return 1;
    }
    return WIFEXITED(etat) ? WEXITSTATUS(etat) : 1;
}
